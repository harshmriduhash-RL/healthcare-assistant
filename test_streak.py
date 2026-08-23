import asyncio
from app.db.session import AsyncSessionLocal
from app.db.models import User, Medicine, Dosage, Notification
from sqlalchemy import select

async def run_test():
    async with AsyncSessionLocal() as db:
        # Get the testuser
        res = await db.execute(select(User).where(User.username == 'testuser'))
        u = res.scalar_one_or_none()
        if not u:
            print("No testuser found")
            return
            
        print("User:", u.id)
        
        # Add a medicine
        med = Medicine(user_id=u.id, name="Test Med", supply_count=10, refill_threshold=2)
        db.add(med)
        await db.commit()
        await db.refresh(med)
        print("Created medicine:", med.id, "streak:", med.current_streak)
        
        # Add a notification
        notif = Notification(user_id=u.id, notification_type="dosage_due", title="test",
            action_payload={"action": "mark_taken", "medicine_id": med.id, "dosage_id": "dummy_dosage"})
        db.add(notif)
        await db.commit()
        await db.refresh(notif)
        print("Created notification:", notif.id)

if __name__ == "__main__":
    asyncio.run(run_test())
