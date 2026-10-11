"""NexgloTV approved device/app directory and compatibility gating.

Only verified, approved apps with official download links are sent to customers.
Disabled entries trigger human compatibility check, not fake instructions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

DEFAULT_APP_DIR_PATH = Path(__file__).resolve().parent.parent / "data" / "approved_apps.json"


@dataclass
class ApprovedApp:
    """A verified, approved app for a specific platform."""
    platform: str              # e.g., "android_phone", "smart_tv_samsung"
    os: str                    # e.g., "Android", "Tizen"
    supported_models: list[str]  # Empty = all models for this platform
    app_name: Optional[str]    # Official app name (None if not yet verified)
    official_download_url: Optional[str]  # Play Store, App Store, Galaxy Store, etc.
    app_icon_url: Optional[str]  # Approved icon/media URL
    instructions: Optional[str]  # Platform-specific install steps (max 6 short steps)
    verified_by: Optional[str]  # Staff member who verified
    verified_at: Optional[str]  # ISO timestamp
    enabled: bool = False       # Only True when all fields verified

    def is_ready(self) -> bool:
        """True if this app can be sent to a customer."""
        return self.enabled and bool(self.app_name) and bool(self.official_download_url)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovedApp":
        return cls(**data)


class DeviceAppDirectory:
    """Loads and manages the approved apps directory."""

    def __init__(self, path: Path = DEFAULT_APP_DIR_PATH):
        self.path = Path(path)
        self._apps: dict[str, ApprovedApp] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._create_example()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for platform, app_data in data.items():
                self._apps[platform] = ApprovedApp.from_dict(app_data)
        except Exception:
            # If corrupt, start fresh with example
            self._create_example()

    def _create_example(self) -> None:
        """Create an example file with all platforms disabled."""
        example = {
            "android_phone": {
                "platform": "android_phone",
                "os": "Android",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "iphone_ipad": {
                "platform": "iphone_ipad",
                "os": "iOS / iPadOS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "smart_tv_samsung": {
                "platform": "smart_tv_samsung",
                "os": "Tizen",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "smart_tv_lg": {
                "platform": "smart_tv_lg",
                "os": "webOS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "smart_tv_android": {
                "platform": "smart_tv_android",
                "os": "Android TV / Google TV",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "fire_stick": {
                "platform": "fire_stick",
                "os": "Fire OS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "tablet_android": {
                "platform": "tablet_android",
                "os": "Android",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "tablet_ipad": {
                "platform": "tablet_ipad",
                "os": "iPadOS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "laptop_windows": {
                "platform": "laptop_windows",
                "os": "Windows",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "laptop_mac": {
                "platform": "laptop_mac",
                "os": "macOS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "android_tv_box": {
                "platform": "android_tv_box",
                "os": "Android TV",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "roku": {
                "platform": "roku",
                "os": "Roku OS",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
            "other": {
                "platform": "other",
                "os": "Unknown",
                "supported_models": [],
                "app_name": None,
                "official_download_url": None,
                "app_icon_url": None,
                "instructions": None,
                "verified_by": None,
                "verified_at": None,
                "enabled": False,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(example, indent=2, ensure_ascii=False), encoding="utf-8")
        self._apps = {k: ApprovedApp.from_dict(v) for k, v in example.items()}

    def get_app(self, platform: str) -> Optional[ApprovedApp]:
        return self._apps.get(platform)

    def get_ready_app(self, platform: str) -> Optional[ApprovedApp]:
        """Get app only if it's verified and enabled."""
        app = self._apps.get(platform)
        if app and app.is_ready():
            return app
        return None

    def find_app_for_device(self, device_id: str, model: str = "") -> Optional[ApprovedApp]:
        """Map customer device selection to the best matching approved app."""
        # Map device catalog IDs to app directory platforms
        platform_map = {
            "android_phone": "android_phone",
            "iphone_ipad": "iphone_ipad",
            "smart_tv": None,  # Needs model to determine Samsung/LG/Android TV
            "fire_stick": "fire_stick",
            "tablet": None,  # Needs model for Android vs iPad
            "laptop": None,  # Needs model for Windows vs Mac
            "android_tv_box": "android_tv_box",
            "roku": "roku",
            "other": "other",
        }

        platform = platform_map.get(device_id)
        if platform:
            return self.get_ready_app(platform)

        # Smart TV - try to detect from model
        if device_id == "smart_tv":
            model_lower = model.lower()
            if any(x in model_lower for x in ["samsung", "tizen"]):
                return self.get_ready_app("smart_tv_samsung")
            elif any(x in model_lower for x in ["lg", "webos"]):
                return self.get_ready_app("smart_tv_lg")
            elif any(x in model_lower for x in ["android tv", "google tv", "sony", "philips", "xiaomi", "hisense", "tcl"]):
                return self.get_ready_app("smart_tv_android")
            # Unknown TV brand - return None to trigger compatibility check
            return None

        # Tablet - try to detect from model
        if device_id == "tablet":
            model_lower = model.lower()
            if any(x in model_lower for x in ["ipad", "apple"]):
                return self.get_ready_app("tablet_ipad")
            return self.get_ready_app("tablet_android")

        # Laptop - try to detect from model
        if device_id == "laptop":
            model_lower = model.lower()
            if any(x in model_lower for x in ["mac", "macbook", "apple"]):
                return self.get_ready_app("laptop_mac")
            return self.get_ready_app("laptop_windows")

        return None

    def get_all_ready_apps(self) -> dict[str, ApprovedApp]:
        return {k: v for k, v in self._apps.items() if v.is_ready()}

    def update_app(self, platform: str, **kwargs) -> ApprovedApp:
        """Update an app entry (staff use)."""
        if platform not in self._apps:
            raise ValueError(f"Unknown platform: {platform}")
        app = self._apps[platform]
        for key, value in kwargs.items():
            if hasattr(app, key):
                setattr(app, key, value)
        self._save()
        return app

    def _save(self) -> None:
        data = {k: v.to_dict() for k, v in self._apps.items()}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Global instance (initialized on import)
device_app_directory = DeviceAppDirectory()