"""Transactional persistence; SQLite is supported only for local fixture tests."""
import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, JSON, UniqueConstraint, select, insert, update, delete, text
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
reports = Table('reports', metadata, Column('id', String, primary_key=True), Column('day', String, nullable=False), Column('revision', Integer, nullable=False), Column('payload', JSON, nullable=False), UniqueConstraint('day', 'revision'))
tasks = Table('tasks', metadata, Column('id', String, primary_key=True), Column('day', String), Column('status', String), Column('error', String), Column('updated_at', String))
checkpoints = Table('checkpoints', metadata, Column('key', String, primary_key=True), Column('payload', JSON))
deliveries = Table('deliveries', metadata, Column('id', String, primary_key=True), Column('day', String), Column('channel', String), Column('digest', String), Column('status', String), Column('result', JSON), UniqueConstraint('day', 'channel', 'digest'))
parts = Table('delivery_parts', metadata, Column('key', String, primary_key=True), Column('payload', JSON))
states = Table('rule_states', metadata, Column('day', String, primary_key=True), Column('payload', JSON))


class Repository:
    def __init__(self, url):
        self.engine = create_engine(url, pool_pre_ping=True)

    def initialize(self):
        metadata.create_all(self.engine)

    @contextmanager
    def acquire_day(self, day):
        if self.engine.dialect.name != 'postgresql':
            yield
            return
        key = int.from_bytes(hashlib.sha256(str(day).encode()).digest()[:8], 'big', signed=True)
        with self.engine.connect() as conn:
            acquired = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
            conn.commit()
            if not acquired:
                raise ValueError('day_already_running')
            try:
                yield
            finally:
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                conn.commit()

    def get_report(self, day):
        with self.engine.connect() as conn:
            return conn.execute(select(reports.c.payload).where(reports.c.day == str(day)).order_by(reports.c.revision.desc()).limit(1)).scalar()

    def publish_report(self, day, payload, state=None):
        with self.engine.begin() as conn:
            revision = conn.execute(select(reports.c.revision).where(reports.c.day == str(day)).order_by(reports.c.revision.desc()).limit(1)).scalar() or 0
            conn.execute(insert(reports).values(id=str(uuid.uuid4()), day=str(day), revision=revision+1, payload=payload))
            if state is not None:
                conn.execute(delete(states).where(states.c.day == str(day)))
                conn.execute(insert(states).values(day=str(day), payload=state))
                from datetime import timedelta
                next_day = str(day+timedelta(days=1))
                next_state = conn.execute(select(states.c.payload).where(states.c.day == next_day)).scalar()
                if next_state is not None:
                    conn.execute(update(states).where(states.c.day == next_day).values(payload={**next_state, '_needs_recompute': True}))

    def history(self, day, days=7):
        from datetime import timedelta
        return [r for i in range(1, days+1) if (r := self.get_report(day-timedelta(days=i)))]

    def create_task(self, day):
        task_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(tasks).values(id=task_id, day=str(day), status='queued', updated_at=datetime.now(timezone.utc).isoformat()))
        return task_id

    def update_task(self, task_id, status, error=None):
        with self.engine.begin() as conn:
            conn.execute(update(tasks).where(tasks.c.id == task_id).values(status=status, error=error, updated_at=datetime.now(timezone.utc).isoformat()))

    def get_task(self, task_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().first()
            return dict(row) if row else None

    def pending(self):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(tasks).where(tasks.c.status.in_(['queued', 'running']))).mappings()]

    def save_checkpoint(self, task_id, key, payload):
        with self.engine.begin() as conn:
            conn.execute(delete(checkpoints).where(checkpoints.c.key == key))
            conn.execute(insert(checkpoints).values(key=key, payload=payload))

    def checkpoint(self, key):
        with self.engine.connect() as conn:
            return conn.execute(select(checkpoints.c.payload).where(checkpoints.c.key == key)).scalar()

    def save_state(self, day, payload):
        with self.engine.begin() as conn:
            conn.execute(delete(states).where(states.c.day == str(day)))
            conn.execute(insert(states).values(day=str(day), payload=payload))

    def get_state(self, day):
        with self.engine.connect() as conn:
            return conn.execute(select(states.c.payload).where(states.c.day == str(day))).scalar() or {}

    def clear_checkpoints(self, prefix):
        with self.engine.begin() as conn:
            conn.execute(delete(checkpoints).where(checkpoints.c.key.startswith(prefix)))

    def claim_delivery(self, day, channel, digest):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(deliveries).values(id=str(uuid.uuid4()), day=day, channel=channel, digest=digest, status='sending'))
            return True
        except IntegrityError:
            return False

    def finish_delivery(self, day, channel, digest, result):
        with self.engine.begin() as conn:
            conn.execute(update(deliveries).where(deliveries.c.day == day, deliveries.c.channel == channel, deliveries.c.digest == digest).values(status=result['status'], result=result))

    def record_part(self, day, digest, index, result):
        with self.engine.begin() as conn:
            conn.execute(insert(parts).values(key=f'{day}:{digest}:{index}', payload=result))

    def recover_deliveries(self):
        with self.engine.begin() as conn:
            conn.execute(update(deliveries).where(deliveries.c.status == 'sending').values(status='unknown', result={'error': 'process_interrupted'}))
