"""Durable reservations survive failed requests and process restarts."""

import json
import sqlite3
import time
from contextlib import closing, contextmanager

from .configuration import (
    COST_LIMIT_NANO_USD,
    INPUT_LIMIT,
    INPUT_NANO_USD_PER_TOKEN,
    OUTPUT_LIMIT,
    OUTPUT_NANO_USD_PER_TOKEN,
    PURPOSES,
)


class BudgetExceeded(RuntimeError):
    pass


def _cost(input_tokens, output_tokens):
    return input_tokens * INPUT_NANO_USD_PER_TOKEN + output_tokens * OUTPUT_NANO_USD_PER_TOKEN


class BudgetLedger:
    def __init__(self, configuration, *, clock=time.time):
        self.configuration = configuration
        self.path = configuration.ledger_path
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as database:
            database.executescript(
                "CREATE TABLE IF NOT EXISTS configuration (value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS episodes ("
                "id TEXT PRIMARY KEY, started REAL NOT NULL);"
                "CREATE TABLE IF NOT EXISTS calls ("
                "id INTEGER PRIMARY KEY, purpose TEXT NOT NULL, episode_id TEXT,"
                "request_sha256 TEXT NOT NULL, started REAL NOT NULL,"
                "input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,"
                "reserved_input INTEGER NOT NULL, reserved_output INTEGER NOT NULL,"
                "status TEXT NOT NULL, model TEXT, stop_reason TEXT);"
            )
            description = json.dumps(configuration.describe(), sort_keys=True)
            rows = database.execute("SELECT value FROM configuration").fetchall()
            if not rows:
                database.execute("INSERT INTO configuration VALUES (?)", (description,))
            elif len(rows) != 1 or rows[0][0] != description:
                raise ValueError("Ledger belongs to a different model configuration")
            if configuration.episode_id is not None:
                database.execute(
                    "INSERT OR IGNORE INTO episodes VALUES (?, ?)",
                    (configuration.episode_id, self.clock()),
                )

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=0)) as database:
            database.row_factory = sqlite3.Row
            database.execute("PRAGMA synchronous=FULL")
            with database:
                yield database

    def _episode_time(self, database):
        episode_id = self.configuration.episode_id
        if episode_id is None:
            raise ValueError("Grounding requires an explicitly started episode")
        started = database.execute(
            "SELECT started FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()[0]
        elapsed = self.clock() - started
        if elapsed < 0 or elapsed >= 1200:
            raise BudgetExceeded("execution_wall_seconds")
        return elapsed

    def reserve(self, purpose, input_tokens, output_tokens, request_sha256):
        if purpose not in PURPOSES:
            raise ValueError("Unsupported model request purpose")
        if any(type(value) is not int or value <= 0 for value in (input_tokens, output_tokens)):
            raise ValueError("Positive integer token reservations are required")
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            rows = database.execute("SELECT * FROM calls ORDER BY id").fetchall()
            if any(row["status"] not in ("completed",) for row in rows):
                raise BudgetExceeded("unsettled_or_failed_model_request")
            candidates = [row for row in rows if row["purpose"] != "observation_grounding"]
            if purpose == "candidate_discovery" and candidates:
                raise BudgetExceeded("candidate_initial_request_already_used")
            if purpose == "candidate_repair" and len(candidates) != 1:
                raise BudgetExceeded("candidate_repair_requires_one_initial_request")
            if purpose != "observation_grounding" and len(candidates) >= 2:
                raise BudgetExceeded("candidate_requests_per_condition")
            episode_id = None
            if purpose == "observation_grounding":
                self._episode_time(database)
                episode_id = self.configuration.episode_id
                if sum(row["episode_id"] == episode_id for row in rows) >= 64:
                    raise BudgetExceeded("model_requests_per_execution_episode")
            total_input = input_tokens + sum(row["input_tokens"] for row in rows)
            total_output = output_tokens + sum(row["output_tokens"] for row in rows)
            if total_input > INPUT_LIMIT:
                raise BudgetExceeded("model_input_tokens_per_condition")
            if total_output > OUTPUT_LIMIT:
                raise BudgetExceeded("model_output_tokens_per_condition")
            if _cost(total_input, total_output) > COST_LIMIT_NANO_USD:
                raise BudgetExceeded("estimated_model_cost_usd_per_condition")
            cursor = database.execute(
                "INSERT INTO calls (purpose,episode_id,request_sha256,started,"
                "input_tokens,output_tokens,reserved_input,reserved_output,status) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    purpose,
                    episode_id,
                    request_sha256,
                    self.clock(),
                    input_tokens,
                    output_tokens,
                    input_tokens,
                    output_tokens,
                    "reserved",
                ),
            )
            return cursor.lastrowid

    def settle(self, call_id, *, model, usage):
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
            if row is None or row["status"] != "reserved":
                raise ValueError("Only an issued, pending reservation can settle")
            counts = None if usage is None else (usage.input_tokens, usage.output_tokens)
            reason = None
            if model != self.configuration.model:
                reason = "unexpected_model_revision"
            elif counts is None:
                reason = "missing_model_usage"
            elif any(type(value) is not int or value < 0 for value in counts):
                reason = "invalid_model_usage"
            elif counts[0] > row["reserved_input"] or counts[1] > row["reserved_output"]:
                reason = "model_usage_exceeded_reservation"
            if reason is not None:
                charged = (row["reserved_input"], row["reserved_output"])
                if counts is not None and all(
                    type(value) is int and value >= 0 for value in counts
                ):
                    charged = tuple(
                        max(bound, actual) for bound, actual in zip(charged, counts, strict=True)
                    )
                database.execute(
                    "UPDATE calls SET status='failed',model=?,stop_reason=?,"
                    "input_tokens=?,output_tokens=? WHERE id=?",
                    (model, reason, *charged, call_id),
                )
            else:
                database.execute(
                    "UPDATE calls SET status='completed',model=?,input_tokens=?,"
                    "output_tokens=? WHERE id=?",
                    (model, *counts, call_id),
                )
        if reason is not None:
            raise BudgetExceeded(reason)

    def fail(self, call_id, reason):
        with self._connect() as database:
            database.execute(
                "UPDATE calls SET status='failed',stop_reason=? WHERE id=? AND status='reserved'",
                (reason, call_id),
            )

    def remaining_seconds(self):
        with self._connect() as database:
            return 1200 - self._episode_time(database)

    def describe(self):
        with self._connect() as database:
            calls = [dict(row) for row in database.execute("SELECT * FROM calls ORDER BY id")]
        input_tokens = sum(row["input_tokens"] for row in calls)
        output_tokens = sum(row["output_tokens"] for row in calls)
        return {
            "calls": calls,
            "charged_or_reserved_input_tokens": input_tokens,
            "charged_or_reserved_output_tokens": output_tokens,
            "charged_or_reserved_nano_usd": _cost(input_tokens, output_tokens),
        }
