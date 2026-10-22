PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "engine": {
            "type": "string",
            "const": "fav8_plus",
            "default": "fav8_plus",
        },
        "mode": {
            "type": "string",
            "enum": ["auto", "default", "oceano", "fogo", "natureza", "realismo", "quadrinhos"],
            "default": "auto",
        },
        "dark_fabric": {"type": "boolean", "default": True},
        "key_plate_enabled": {"type": "boolean", "default": False},
        "key_plate_mode": {
            "type": "string",
            "enum": ["auto", "override"],
            "default": "auto",
        },
        "key_plate_tonal_threshold": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 1,
            "default": 0.38,
        },
        "key_plate_gamma": {
            "type": "number",
            "exclusiveMinimum": 0,
            "default": 0.88,
        },
        "key_plate_chroma_protection": {
            "type": "number",
            "minimum": 0,
            "default": 0.035,
        },
        "key_plate_min_density": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0,
        },
        "key_plate_max_density": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 1,
        },
        "key_plate_merge_compatible_dark": {"type": "boolean", "default": False},
        "joint_cleanup_mode": {
            "type": "string",
            "enum": ["off", "auto", "manual"],
            "default": "off",
        },
        "joint_cleanup_threshold": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.03,
        },
        "joint_cleanup_min_area_px": {
            "type": "integer",
            "minimum": 1,
            "default": 4,
        },
        "joint_cleanup_dpi": {"type": ["number", "null"], "exclusiveMinimum": 0},
        "joint_cleanup_lpi": {"type": ["number", "null"], "exclusiveMinimum": 0},
    },
    "additionalProperties": False,
}

