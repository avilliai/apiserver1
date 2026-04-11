"""
scripts/create_admin.py
Run once to create the first admin user (no invite code needed).

Usage:
    cd backend
    python ../scripts/create_admin.py --username admin --password your_password
"""
import asyncio, argparse, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '', 'backend'))

from core.database import AsyncSessionLocal, engine, Base, User
from core.auth_utils import hash_password
from sqlalchemy import select

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', required=True)
    args = parser.parse_args()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.username == args.username))
        if existing.scalar_one_or_none():
            print(f"User '{args.username}' already exists.")
            return

        user = User(
            username=args.username,
            hashed_password=hash_password(args.password),
            is_admin=True,
        )
        user.quota = {}
        db.add(user)
        await db.commit()
        print(f"✓ Admin user '{args.username}' created successfully.")

asyncio.run(main())
