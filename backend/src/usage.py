import hashlib

def fit(rows):
    # rows为(接收单位,申领粒数,实播粒数)，仅实播已登记的单子参与；利用率=Σ实播/Σ申领，裁到0–1
    agg={}
    for recipient,claimed,sown in rows:
        a=agg.setdefault(recipient,{'records':0,'claimed':0,'sown':0})
        a['records']+=1;a['claimed']+=claimed;a['sown']+=sown
    return {r:{'records':a['records'],'claimed':a['claimed'],'sown':a['sown'],'ratio':max(0.0,min(1.0,a['sown']/a['claimed']))}for r,a in agg.items()if a['claimed']>0}
def predict(claimed,ratio):return max(0,min(claimed,int(claimed*ratio+.5)))
def token(accession_id,pairs):
    raw='|'.join(f'{i}:{c}'for i,c in sorted(pairs))
    return hashlib.sha256(f'{accession_id}|{raw}'.encode()).hexdigest()
def allocate(surplus,weights,caps,groups=None,group_caps=None):
    # 保底外余量按权重比例水注分配；逐项不超申领上限，同组(种批)合计不超库存，Σ≤surplus；整数结果确定
    n=len(caps);alloc=[0]*n
    if surplus<=0 or n==0:return alloc
    if sum(weights)<=0:weights=list(caps)
    cur=[0.0]*n;rem=float(surplus);gsum=[0.0]*len(group_caps)if groups is not None else None
    def room(i):
        r=caps[i]-cur[i]
        if groups is not None:r=min(r,group_caps[groups[i]]-gsum[groups[i]])
        return max(0.0,r)
    active=[i for i in range(n)if room(i)>1e-9]
    while rem>1e-9 and active:
        w=sum(weights[i]for i in active)
        share={i:(rem*weights[i]/w if w>0 else rem/len(active))for i in active}
        if groups is not None:
            # 组内份额同比例缩放，组合计不超库存，与处理顺序无关
            for g in range(len(group_caps)):
                idx=[i for i in active if groups[i]==g]
                if not idx:continue
                want=sum(share[i]for i in idx);roomg=group_caps[g]-gsum[g]
                if want>roomg:
                    for i in idx:share[i]=share[i]*max(0.0,roomg)/want if want>0 else 0.0
        nxt=[]
        for i in active:
            take=min(share[i],caps[i]-cur[i]);cur[i]+=take;rem-=take
            if groups is not None:gsum[groups[i]]+=take
            if room(i)>1e-9:nxt.append(i)
        if len(nxt)==len(active):break
        active=nxt
    alloc=[int(x)for x in cur];left=surplus-sum(alloc)
    def iroom(i):
        r=caps[i]-alloc[i]
        if groups is not None:r=min(r,group_caps[groups[i]]-sum(alloc[j]for j in range(n)if groups[j]==groups[i]))
        return max(0,r)
    order=sorted(range(n),key=lambda i:(-(cur[i]-alloc[i]),i))
    while left>0:
        progressed=False
        for i in order:
            if left==0:break
            if iroom(i)>0:alloc[i]+=1;left-=1;progressed=True
        if not progressed:break
    return alloc
