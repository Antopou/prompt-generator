QUALITY_BASE = [
    "masterpiece", "best quality", "highly detailed",
    "beautiful lighting", "sharp focus",
]

SCENES = {
    "portrait": {
        "framing_force": ["upper body"],
        "pose_force": ["looking at viewer"],
        "expression_pick": 1,
        "outfit_pick": 1,
        "background_force": ["simple background", "white background"],
        "extra": ["detailed face", "detailed eyes"],
        "size": "832x1216",
    },
    "pose": {
        "framing_force": ["full body"],
        "pose_pick": 2,
        "expression_pick": 1,
        "outfit_pick": 1,
        "background_force": ["simple background"],
        "extra": ["dynamic pose"],
        "size": "832x1216",
    },
    "situation": {
        "framing_force": ["cowboy shot"],
        "pose_pick": 1,
        "expression_pick": 1,
        "outfit_pick": 1,
        "background_pick": 1,
        "extra": ["cinematic lighting", "depth of field"],
        "size": "1024x1024",
    },
}

NEGATIVE = (
    "worst quality, low quality, bad anatomy, bad hands, bad proportions, "
    "watermark, signature, blurry, extra digits, missing digits, jpeg artifacts"
)
