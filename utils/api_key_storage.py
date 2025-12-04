"""
Secure API key storage with hashing and timing-safe validation.

Security features:
- Keys are hashed with SHA-256 + unique salt before storage
- Plaintext keys are NEVER stored after generation
- Validation uses constant-time comparison (timing-safe)
- File permissions restricted (0o600 on Unix)
"""
import json
import os
import platform
import secrets
import hashlib
import hmac
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from settings import API_KEYS_FILE

logger = logging.getLogger(__name__)

# Key format constants
KEY_PREFIX = "llmux-"
KEY_RANDOM_BYTES = 32  # 256 bits of entropy
KEY_PREFIX_DISPLAY_LENGTH = 12  # Show first 12 chars for identification (prefix + some random)


class APIKeyStorage:
    """Secure API key storage with hashing"""

    def __init__(self, keys_file: Optional[str] = None):
        self.keys_path = Path(keys_file if keys_file else API_KEYS_FILE)
        self._ensure_secure_directory()

    def _ensure_secure_directory(self):
        """Create parent directory with secure permissions"""
        parent_dir = self.keys_path.parent
        if not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)
            if platform.system() != "Windows":
                os.chmod(parent_dir, 0o700)

    def _generate_key(self) -> str:
        """Generate a cryptographically secure API key"""
        random_bytes = secrets.token_bytes(KEY_RANDOM_BYTES)
        random_part = base64.urlsafe_b64encode(random_bytes).decode('ascii').rstrip('=')
        return f"{KEY_PREFIX}{random_part}"

    def _hash_key(self, key: str, salt: bytes) -> str:
        """Hash a key with salt using SHA-256"""
        key_bytes = key.encode('utf-8')
        hash_input = salt + key_bytes
        return hashlib.sha256(hash_input).hexdigest()

    def _generate_salt(self) -> bytes:
        """Generate a random salt for key hashing"""
        return secrets.token_bytes(16)

    def _generate_key_id(self) -> str:
        """Generate a unique key ID"""
        return secrets.token_hex(8)

    def _load_data(self) -> Dict[str, Any]:
        """Load keys data from storage"""
        if not self.keys_path.exists():
            return {"api_keys": {}}
        try:
            data = json.loads(self.keys_path.read_text())
            if "api_keys" not in data:
                data["api_keys"] = {}
            return data
        except (json.JSONDecodeError, IOError):
            return {"api_keys": {}}

    def _save_data(self, data: Dict[str, Any]):
        """Save keys data to storage with secure permissions"""
        self.keys_path.write_text(json.dumps(data, indent=2))
        if platform.system() != "Windows":
            os.chmod(self.keys_path, 0o600)

    def create_key(self, name: str) -> Tuple[str, str]:
        """
        Create a new API key.

        Returns:
            Tuple of (key_id, plaintext_key)
            NOTE: The plaintext key is returned ONLY ONCE and should be shown to user
        """
        # Generate key and metadata
        plaintext_key = self._generate_key()
        key_id = self._generate_key_id()
        salt = self._generate_salt()
        key_hash = self._hash_key(plaintext_key, salt)

        # Load, update, save
        data = self._load_data()
        data["api_keys"][key_id] = {
            "name": name,
            "key_hash": key_hash,
            "salt": base64.b64encode(salt).decode('ascii'),
            "key_prefix": plaintext_key[:KEY_PREFIX_DISPLAY_LENGTH],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used_at": None,
            "usage_count": 0
        }
        self._save_data(data)

        logger.info(f"API key created: id={key_id}, name={name}")
        return key_id, plaintext_key

    def validate_key(self, key: str) -> Optional[str]:
        """
        Validate an API key using timing-safe comparison.

        Returns:
            key_id if valid, None if invalid
        """
        # Quick format validation (not timing-sensitive, fails fast)
        if not key or not key.startswith(KEY_PREFIX):
            logger.warning("API key validation failed: invalid format")
            return None

        data = self._load_data()

        # Check against all stored keys using timing-safe comparison
        for key_id, key_data in data["api_keys"].items():
            salt = base64.b64decode(key_data["salt"])
            stored_hash = key_data["key_hash"]
            computed_hash = self._hash_key(key, salt)

            # Timing-safe comparison
            if hmac.compare_digest(stored_hash, computed_hash):
                # Update usage statistics
                key_data["last_used_at"] = datetime.now(timezone.utc).isoformat()
                key_data["usage_count"] = key_data.get("usage_count", 0) + 1
                self._save_data(data)

                logger.debug(f"API key validated: id={key_id}")
                return key_id

        # Log failure with partial key only
        prefix_display = key[:KEY_PREFIX_DISPLAY_LENGTH] if len(key) >= KEY_PREFIX_DISPLAY_LENGTH else key
        logger.warning(f"API key validation failed: key not found (prefix={prefix_display})")
        return None

    def delete_key(self, key_id: str) -> bool:
        """Delete an API key by ID"""
        data = self._load_data()
        if key_id in data["api_keys"]:
            name = data["api_keys"][key_id]["name"]
            del data["api_keys"][key_id]
            self._save_data(data)
            logger.info(f"API key deleted: id={key_id}, name={name}")
            return True
        return False

    def rename_key(self, key_id: str, new_name: str) -> bool:
        """Rename an API key"""
        data = self._load_data()
        if key_id in data["api_keys"]:
            old_name = data["api_keys"][key_id]["name"]
            data["api_keys"][key_id]["name"] = new_name
            self._save_data(data)
            logger.info(f"API key renamed: id={key_id}, {old_name} -> {new_name}")
            return True
        return False

    def list_keys(self) -> List[Dict[str, Any]]:
        """List all API keys (without exposing hashes)"""
        data = self._load_data()
        keys = []
        for key_id, key_data in data["api_keys"].items():
            keys.append({
                "id": key_id,
                "name": key_data["name"],
                "key_prefix": key_data["key_prefix"],
                "created_at": key_data["created_at"],
                "last_used_at": key_data["last_used_at"],
                "usage_count": key_data.get("usage_count", 0)
            })
        # Sort by created_at (newest first)
        return sorted(keys, key=lambda x: x.get("created_at", ""), reverse=True)

    def get_key_by_id(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get key metadata by ID (without hash)"""
        data = self._load_data()
        if key_id in data["api_keys"]:
            key_data = data["api_keys"][key_id]
            return {
                "id": key_id,
                "name": key_data["name"],
                "key_prefix": key_data["key_prefix"],
                "created_at": key_data["created_at"],
                "last_used_at": key_data["last_used_at"],
                "usage_count": key_data.get("usage_count", 0)
            }
        return None

    def has_keys(self) -> bool:
        """Check if any API keys exist"""
        data = self._load_data()
        return len(data["api_keys"]) > 0

    def get_key_count(self) -> int:
        """Get the number of stored API keys"""
        data = self._load_data()
        return len(data["api_keys"])
