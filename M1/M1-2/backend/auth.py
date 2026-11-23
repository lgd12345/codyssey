"""Password hashing and session lifetime for the local member login."""
import hashlib

SESSION_SECONDS = 8 * 60 * 60


def hash_password(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt),
                          n=2**15, r=8, p=3, maxmem=64 * 1024 * 1024).hex()
