from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class WantedCriminal(Base):
    __tablename__ = "wanted_criminals"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 10", name="ck_criminal_difficulty"),
        CheckConstraint("reward >= 0", name="ck_criminal_reward"),
        CheckConstraint(
            "(last_latitude IS NULL) = (last_longitude IS NULL)",
            name="ck_criminal_coords_pair",
        ),
        CheckConstraint("last_latitude BETWEEN -90 AND 90", name="ck_criminal_lat"),
        CheckConstraint("last_longitude BETWEEN -180 AND 180", name="ck_criminal_lon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nickname: Mapped[str] = mapped_column(String(120), nullable=False)
    reward: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_crew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escape_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    hunts: Mapped[list["HuntLog"]] = relationship(
        back_populates="criminal",
        cascade="all, delete-orphan",
        order_by="HuntLog.id",
    )


class HuntLog(Base):
    __tablename__ = "hunt_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criminal_id: Mapped[int] = mapped_column(
        ForeignKey("wanted_criminals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    criminal: Mapped[WantedCriminal] = relationship(back_populates="hunts")
