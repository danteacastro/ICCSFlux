#!/usr/bin/env python3
"""Reset admin password to iccsadmin"""
import bcrypt
import json

users_file = 'data/users.json'
with open(users_file, 'r') as f:
    users = json.load(f)

# Reset admin password
new_hash = bcrypt.hashpw(b'iccsadmin', bcrypt.gensalt()).decode()
users['admin']['password_hash'] = new_hash
users['admin']['failed_attempts'] = 0

with open(users_file, 'w') as f:
    json.dump(users, f, indent=2)

print(f"Admin password reset to 'iccsadmin'")
print(f"New hash: {new_hash}")
