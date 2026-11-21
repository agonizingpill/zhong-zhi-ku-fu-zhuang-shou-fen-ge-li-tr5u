from sqlalchemy import select,func,text
from .db import Base,engine,Session
from .models import *
from .auth import hashed

def migrate():
    # 老库补缺共享批次列；新库由create_all一次建全
    if engine.dialect.name!='mysql':return
    with engine.begin() as c:
        cols={r[1] for r in c.execute(text('SHOW COLUMNS FROM distributions'))}
        for col in ('allocated','sown','batch_id'):
            if col not in cols:c.execute(text(f'ALTER TABLE distributions ADD COLUMN {col} INT NULL'))

def seed():
    Base.metadata.create_all(engine);migrate()
    with Session() as s:
        for role in ('operator','supervisor','viewer'):
            email=role+'@qinghe.demo'
            if not s.scalar(select(User).where(User.email==email)):s.add(User(email=email,role=role,password_hash=hashed('Seeds2026!')))
        a=s.scalar(select(Accession).where(Accession.code=='QH-021'))
        if not a:a=Accession(code='QH-021',crop='青豆',name='青禾早熟青豆',origin='青禾北圃2023采集',minimum=300);s.add(a);s.flush()
        for code,generation,available in [('QH-021-G3',3,960),('QH-021-POLLEN',3,400)]:
            if not s.scalar(select(Lot).where(Lot.code==code)):s.add(Lot(accession_id=a.id,code=code,generation=generation,available=available,stored_months=36,temperature=4,initial_rate=94))
        other=s.scalar(select(Accession).where(Accession.code=='QH-087'))
        if not other:other=Accession(code='QH-087',crop='青豆',name='异源晚熟青豆',origin='南坡异源对照',minimum=300);s.add(other);s.flush()
        if not s.scalar(select(Lot).where(Lot.code=='QH-087-G2')):s.add(Lot(accession_id=other.id,code='QH-087-G2',generation=2,available=800,stored_months=18,temperature=-8,initial_rate=96))
        for i in range(18):
            code=chr(65+i//6)+str(i%6+1)
            if not s.scalar(select(Plot).where(Plot.code==code)):s.add(Plot(code=code,row=i//6,position=i%6,capacity=250))
        s.flush();lot=s.scalar(select(Lot).where(Lot.code=='QH-021-G3'))
        if not s.scalar(select(GerminationTest).where(GerminationTest.code=='GT-SEED-80')):s.add(GerminationTest(lot_id=lot.id,code='GT-SEED-80',sampled=100,germinated=80,state='recorded'))
        # 上一季共享归档：已收讫，实播有报有未报；不再次扣种、不回填签发快照
        for code,recipient,seeds,sown,purpose in [('SH-QH021-2025A','青禾协作育种圃',200,150,'2025春性状观察（归档记录）'),('SH-QH021-2025B','北岭保种圃',200,196,'2025春保种扩繁（归档记录）'),('SH-QH021-2025C','青禾协作育种圃',300,None,'2025秋性状复核（归档，实播未报）')]:
            if not s.scalar(select(Distribution).where(Distribution.code==code)):s.add(Distribution(code=code,lot_id=lot.id,recipient=recipient,seeds=seeds,allocated=seeds,sown=sown,purpose=purpose,state='received'))
        s.commit();return {cls.__tablename__:s.scalar(select(func.count()).select_from(cls))for cls in (User,Accession,Lot,GerminationTest,Regeneration,Plot,Flowering,Pollination,Harvest,Distribution,ShareBatch)}
