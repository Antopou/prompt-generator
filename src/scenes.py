"""Scene recipes. All tags come from the dataset — no injected boilerplate."""

SCENES = {
    "portrait": {
        "framing_bias": "upper body",
        "pose_n": 1,
        "expression_n": 1,
        "background_n": 1,
        "outfit": True,
    },
    "pose": {
        "framing_bias": "full body",
        "pose_n": 2,
        "expression_n": 1,
        "background_n": 1,
        "outfit": True,
    },
    "situation": {
        "framing_bias": "cowboy shot",
        "pose_n": 1,
        "expression_n": 1,
        "background_n": 2,
        "outfit": True,
    },
}
