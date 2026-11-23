# Franka Emika Panda simulator model

The Panda robot description and meshes are from MuJoCo Menagerie at commit
[`370c43965323c0944b433b202aac5058b5f907a9`](https://github.com/google-deepmind/mujoco_menagerie/tree/370c43965323c0944b433b202aac5058b5f907a9/franka_emika_panda).
The source describes the Franka Emika Panda and is derived from the Franka ROS
robot description. Its Apache 2.0 license is reproduced in `LICENSE`.

`panda.xml` is the upstream file. `franka_meshes.zip` contains exactly the
meshes that XML references. Each mesh retains its source bytes and is listed in
`mesh_sha256.txt`. The equipment and workcell in `robot_scene.py` are Hanoi
additions. They add the tabletop, fixed cameras and small task-specific inserts
on the fingers. The original arm joint geometry and its actuator limits come
from the pinned model.
