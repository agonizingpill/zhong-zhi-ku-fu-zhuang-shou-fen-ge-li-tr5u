from fastapi import HTTPException
from sqlalchemy import select,func
from .models import Lot,Accession,Distribution,GerminationTest,ShareBatch
from .common import lock,pack,add,audit,reserve
from . import usage

def request(s,d,u):
    if not s.get(Lot,d.lot_id):raise HTTPException(404,'种批不存在')
    x=Distribution(**d.model_dump());audit(s,u,'申请种质共享 '+d.code);return add(s,x)
def latest_test(s,lot_id):
    return s.scalar(select(GerminationTest).where(GerminationTest.lot_id==lot_id,GerminationTest.state=='ready').order_by(GerminationTest.id.desc()))
def fit_rows(s):
    # 未报实播的单子不参与拟合
    return[(x.recipient,x.seeds,x.sown)for x in s.scalars(select(Distribution).where(Distribution.sown.isnot(None))).all()]
def build_plan(s,acc,rows):
    lots={x.id:s.get(Lot,x.lot_id)for x in rows}
    total=int(s.scalar(select(func.sum(Lot.available)).where(Lot.accession_id==acc.id))or 0)
    surplus=max(0,total-acc.minimum);model=usage.fit(fit_rows(s));entries=[]
    lids=sorted({l.id for l in lots.values()});gidx={l:k for k,l in enumerate(lids)};lavail={l.id:l.available for l in lots.values()}
    for x in rows:
        ratio=model.get(x.recipient,{}).get('ratio',1.0)
        entries.append({'distribution_id':x.id,'code':x.code,'recipient':x.recipient,'lot_code':lots[x.id].code,'claimed':x.seeds,'predicted':usage.predict(x.seeds,ratio),'cap':min(x.seeds,lots[x.id].available)})
    alloc=usage.allocate(surplus,[e['predicted']for e in entries],[e['cap']for e in entries],[gidx[lots[x.id].id]for x in rows],[lavail[l]for l in lids])
    for e,a in zip(entries,alloc):e['allocated']=a
    serial=int(s.scalar(select(func.count()).select_from(ShareBatch).where(ShareBatch.accession_id==acc.id))or 0)+1
    return{'accession_id':acc.id,'accession_code':acc.code,'serial':serial,'total':total,'minimum':acc.minimum,'surplus':surplus,'requested_total':sum(e['claimed']for e in entries),'allocated_total':sum(alloc),'entries':entries,'model':{'type':'按单位拟合利用率=Σ实播/Σ申领，预测用种量=申领×利用率；无实播记录单位按全额','recipients':model}}
def plan(s,accession_id):
    acc=s.get(Accession,accession_id)
    if not acc:raise HTTPException(404,'种质不存在')
    rows=s.scalars(select(Distribution).join(Lot,Distribution.lot_id==Lot.id).where(Lot.accession_id==acc.id,Distribution.state=='requested').order_by(Distribution.id)).all()
    if not rows:raise HTTPException(409,'本种质没有待签发申领')
    p=build_plan(s,acc,rows);p['token']=usage.token(acc.id,[(x.id,x.seeds)for x in rows]);return p
def sign(s,d,u):
    acc=lock(s,Accession,d.accession_id)
    ids=sorted(set(d.distribution_ids))
    rows={x.id:x for x in s.scalars(select(Distribution).where(Distribution.id.in_(ids))).all()}
    if len(rows)!=len(ids):raise HTTPException(409,'批次组成已变化，请重新计算分配')
    token=usage.token(acc.id,[(i,rows[i].seeds)for i in ids])
    done=s.scalar(select(ShareBatch).where(ShareBatch.token==token))
    if done:return pack(done)
    ordered=[rows[i]for i in ids];lots={}
    for x in ordered:
        lot=s.get(Lot,x.lot_id);lots[x.id]=lot
        if lot.accession_id!=acc.id:raise HTTPException(409,'申领不属于本种质批次')
        if x.state!='requested':raise HTTPException(409,'批次组成已变化，请重新计算分配')
        test=latest_test(s,lot.id)
        if not test or test.prediction['observed_pct']<80:raise HTTPException(409,'共享种批须独立复测发芽率≥80%，后代不可只用继承先验')
    # 锁内按最新余额重算：抽样先扣种则旧分配失效；整批同事务，要么全签要么回滚
    p=build_plan(s,acc,ordered)
    if p['allocated_total']<=0:raise HTTPException(409,'保底外余量或申领种批库存不足，整批未签发')
    sheet=ShareBatch(code=d.code,accession_id=acc.id,token=token,plan=p['entries'],snapshot={'accession_code':acc.code,'before_total':p['total'],'after_total':p['total']-p['allocated_total'],'minimum':acc.minimum,'surplus':p['surplus'],'requested_total':p['requested_total'],'allocated_total':p['allocated_total'],'model':p['model']})
    s.add(sheet);s.flush()
    for x,e in zip(ordered,p['entries']):
        if not e['allocated']:continue
        x.reserve_snapshot=reserve(s,lots[x.id],e['allocated'])|{'test':pack(latest_test(s,x.lot_id))}
        x.allocated=e['allocated'];x.batch_id=sheet.id;x.state='approved'
    audit(s,u,'主管整批签发共享 '+d.code);return pack(sheet)
def receive(s,id,u):
    d=lock(s,Distribution,id)
    if d.state!='approved':raise HTTPException(409,'只有已签发共享可登记接收，不能重复')
    d.state='received';audit(s,u,'收讫种质共享 '+d.code);return pack(d)
def sow(s,id,d,u):
    x=lock(s,Distribution,id)
    if x.state!='received':raise HTTPException(409,'登记接收后才能填报实播粒数')
    if x.sown is not None:raise HTTPException(409,'实播粒数已登记，不可覆盖')
    if d.sown>(x.allocated if x.allocated is not None else x.seeds):raise HTTPException(409,'实播粒数不能超过实拨粒数')
    x.sown=d.sown;audit(s,u,'登记实播 '+x.code);return pack(x)
