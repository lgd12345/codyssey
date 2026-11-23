"""Create a new deployment account without putting its password on the command line."""
import getpass
import secrets
import sys

from google.api_core.exceptions import AlreadyExists

from backend import auth
from backend.schemas import Login
from backend.storage import store


def main():
    if store.mode != 'firestore':
        sys.exit('STORAGE_BACKEND=firestore is required.')
    username = input('Demo username: ').strip()
    password = getpass.getpass('Demo password (at least 12 characters): ')
    if len(password) < 12 or password != getpass.getpass('Confirm password: '):
        sys.exit('Password did not meet the length or confirmation requirement.')
    account = Login(username=username, password=password)
    salt = secrets.token_hex(16)
    try:
        store.create_firestore_user(account.username, salt, auth.hash_password(account.password, salt))
    except AlreadyExists:
        sys.exit('The account already exists.')
    print('Firestore member created.')


if __name__ == '__main__':
    main()
