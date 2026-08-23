import requests
import asyncio
from app.db.session import AsyncSessionLocal
from app.api.timeline import get_timeline
from app.db.models import User
from sqlalchemy import select

async def run_test():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.username == 'testuser'))
        u = res.scalar_one_or_none()
        if not u:
            print("No testuser found")
            return
            
        events = await get_timeline(user=u, db=db)
        print("Timeline Events:")
        for e in events:
            print(e)

if __name__ == "__main__":
    asyncio.run(run_test())
