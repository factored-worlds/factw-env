"""Observed skill lifecycle implementing subsymbolic.execute_skill."""


class SkillDispatcher:
    def __init__(self, policy):
        self.policy = policy
        self.active = None

    def execute(self, invocation, feedback=None):
        operation, ticket = invocation["operation"], invocation["ticket"]
        if operation == "start":
            if self.active is not None or invocation["skill"] not in self.policy.SKILLS:
                raise ValueError("A skill is already active or unknown")
            self.active = {
                "ticket": ticket,
                "skill": invocation["skill"],
                "baseline": invocation.get("baseline", {}),
            }
            return {**self.active, "status": "running"}
        if self.active is None or ticket != self.active["ticket"]:
            raise ValueError("Skill feedback names an inactive ticket")
        result = dict(self.active)
        if operation == "cancel":
            result.update(status="cancelled", reason=invocation["reason"])
        elif operation == "finish":
            if feedback is None or feedback["tics"] <= invocation["started_tics"]:
                raise ValueError("Skill completion requires new observation evidence")
            if invocation["status"] == "succeeded" and not self.policy.confirmed(
                self.active["skill"],
                feedback["facts"],
                self.active["baseline"],
                feedback.get("estimate"),
            ):
                raise ValueError("Skill postcondition is not observed")
            result.update(status=invocation["status"], reason=invocation["reason"])
        else:
            raise ValueError("Unknown skill lifecycle operation")
        self.active = None
        return result
