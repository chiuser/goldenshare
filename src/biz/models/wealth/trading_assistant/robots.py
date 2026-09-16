"""Private robot configuration evidence (design §7.9–7.11).

No plaintext credentials. Composite references bind owner, object and successful
test; commands still have to lock the robot and check expected configuration.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, LargeBinary,
                        Text, UniqueConstraint, Uuid, text)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


def robot_fk():
    return ForeignKeyConstraint(["owner_user_id", "robot_id"],
        ["app.wealth_ta_robot.owner_user_id", "app.wealth_ta_robot.robot_id"], ondelete="RESTRICT")


def credential_fk(object_column):
    return ForeignKeyConstraint(["owner_user_id", "credential_object_type", object_column, "credential_blob_id"],
        ["app.wealth_ta_credential_blob.owner_user_id", "app.wealth_ta_credential_blob.object_type",
         "app.wealth_ta_credential_blob.object_id", "app.wealth_ta_credential_blob.blob_id"], ondelete="RESTRICT")


class CredentialBlob(Base):
    __tablename__ = "wealth_ta_credential_blob"
    __table_args__ = (
        UniqueConstraint("key_id", "nonce", name="uq_ta_credential_nonce"),
        UniqueConstraint("owner_user_id", "object_type", "object_id", name="uq_ta_credential_object"),
        UniqueConstraint("owner_user_id", "object_type", "object_id", "blob_id", name="uq_ta_credential_reference"),
        CheckConstraint("object_type IN ('CANDIDATE','CONFIG')", name="object_type"),
        CheckConstraint("algorithm_version = 'AES256_GCM_V1' AND length(key_id) > 0 "
                        "AND octet_length(nonce) = 12 AND octet_length(ciphertext) >= 16", name="envelope"),
        {"schema": "app"},
    )
    blob_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"))
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[UUID] = mapped_column(Uuid)
    key_id: Mapped[str] = mapped_column(Text)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    algorithm_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RobotCandidate(Base):
    __tablename__ = "wealth_ta_robot_candidate"
    __table_args__ = (
        robot_fk(), credential_fk("candidate_id"),
        UniqueConstraint("owner_user_id", "robot_id", "candidate_id", name="uq_ta_robot_candidate_identity"),
        ForeignKeyConstraint(["owner_user_id", "robot_id", "expected_config_id"],
            ["app.wealth_ta_robot_config.owner_user_id", "app.wealth_ta_robot_config.robot_id",
             "app.wealth_ta_robot_config.config_id"], name="fk_ta_candidate_expected_config",
            use_alter=True, ondelete="RESTRICT"),
        CheckConstraint("credential_object_type = 'CANDIDATE' AND candidate_version >= 1", name="identity"),
        CheckConstraint("length(btrim(name)) > 0 AND content_digest ~ '^[0-9a-f]{64}$'", name="content"),
        CheckConstraint("cardinality(keywords) <= 10 AND array_position(keywords, NULL) IS NULL", name="keywords"),
        {"schema": "app"},
    )
    candidate_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    robot_id: Mapped[UUID] = mapped_column(Uuid)
    candidate_version: Mapped[int] = mapped_column(BigInteger)
    expected_config_id: Mapped[UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text))
    content_digest: Mapped[str] = mapped_column(Text)
    credential_blob_id: Mapped[UUID] = mapped_column(Uuid)
    credential_object_type: Mapped[str] = mapped_column(Text, server_default="CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RobotTest(Base):
    __tablename__ = "wealth_ta_robot_test"
    __table_args__ = (
        ForeignKeyConstraint(["owner_user_id", "robot_id", "candidate_id"],
            ["app.wealth_ta_robot_candidate.owner_user_id", "app.wealth_ta_robot_candidate.robot_id",
             "app.wealth_ta_robot_candidate.candidate_id"], ondelete="RESTRICT"),
        UniqueConstraint("candidate_id", "attempt_no", name="uq_ta_robot_test_attempt"),
        UniqueConstraint("owner_user_id", "robot_id", "candidate_id", "test_id", "state",
                         name="uq_ta_robot_test_evidence"),
        CheckConstraint("attempt_no >= 1", name="attempt"),
        CheckConstraint("(state = 'IN_FLIGHT' AND completed_at IS NULL AND reason IS NULL) OR "
                        "(state IN ('SUCCEEDED','FAILED','UNKNOWN') AND completed_at IS NOT NULL "
                        "AND completed_at >= started_at)", name="state"),
        {"schema": "app"},
    )
    test_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    robot_id: Mapped[UUID] = mapped_column(Uuid)
    candidate_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_no: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


Index("uq_ta_robot_test_inflight", RobotTest.candidate_id, unique=True,
      postgresql_where=text("state = 'IN_FLIGHT'"))


class RobotConfig(Base):
    __tablename__ = "wealth_ta_robot_config"
    __table_args__ = (
        robot_fk(), credential_fk("config_id"),
        UniqueConstraint("owner_user_id", "robot_id", "config_id", name="uq_ta_robot_config_identity"),
        UniqueConstraint("candidate_id", name="uq_ta_robot_config_candidate"),
        ForeignKeyConstraint(["owner_user_id", "robot_id", "candidate_id", "test_id", "test_state"],
            ["app.wealth_ta_robot_test.owner_user_id", "app.wealth_ta_robot_test.robot_id",
             "app.wealth_ta_robot_test.candidate_id", "app.wealth_ta_robot_test.test_id",
             "app.wealth_ta_robot_test.state"], ondelete="RESTRICT"),
        CheckConstraint("credential_object_type = 'CONFIG' AND test_state = 'SUCCEEDED'", name="evidence"),
        CheckConstraint("length(btrim(name)) > 0", name="name"),
        CheckConstraint("cardinality(keywords) <= 10 AND array_position(keywords, NULL) IS NULL", name="keywords"),
        {"schema": "app"},
    )
    config_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    robot_id: Mapped[UUID] = mapped_column(Uuid)
    candidate_id: Mapped[UUID] = mapped_column(Uuid)
    test_id: Mapped[UUID] = mapped_column(Uuid)
    test_state: Mapped[str] = mapped_column(Text, server_default="SUCCEEDED")
    name: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text))
    credential_blob_id: Mapped[UUID] = mapped_column(Uuid)
    credential_object_type: Mapped[str] = mapped_column(Text, server_default="CONFIG")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
