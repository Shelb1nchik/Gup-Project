from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router = APIRouter(prefix="/shop")


@router.get("/{school_id}")
def get_shop(school_id: int, db: Session = Depends(get_db)):
    return db.query(models.Manufacturer).filter(models.Manufacturer.school_id == school_id).all()


@router.post("/{school_id}/buy/{tank_id}")
def buy_tank(school_id: int, tank_id: int, db: Session = Depends(get_db)):
    school = db.query(models.School).get(school_id)
    tank = db.query(models.Tank).get(tank_id)

    if school.balance < tank.price:
        raise HTTPException(status_code=400, detail="Not enough money")

    school.balance -= tank.price

    new_tank = models.SchoolTank(school_id=school_id, tank_id=tank_id)
    db.add(new_tank)
    db.commit()

    return {"message": "Tank purchased"}