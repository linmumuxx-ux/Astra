class TrafficController:
    def __init__(self):
        self.state='NS_GREEN'; self.elapsed=0; self.q={'NS':0,'EW':0}; self.e={'NS':False,'EW':False}; self.target=None
    def _dir(self,d):
        if d not in ('NS','EW'): raise ValueError('direction')
    def set_queue(self,d,c):
        self._dir(d)
        if type(c) is not int or not 0 <= c <= 20: raise ValueError('count')
        self.q[d]=c
    def set_emergency(self,d,enabled=True):
        self._dir(d)
        if type(enabled) is not bool: raise ValueError('enabled')
        old=self.e[d]; self.e[d]=enabled
        if enabled and not old:
            if self.state=='ALL_RED': self.target=d; self.elapsed=0
            elif self.state != d+'_GREEN': self.state='ALL_RED'; self.target=d; self.elapsed=0
    def tick(self,seconds):
        if type(seconds) is not int or seconds <= 0: raise ValueError('seconds')
        for _ in range(seconds): self._step()
    def _step(self):
        self.elapsed += 1
        if self.state=='ALL_RED':
            if self.elapsed >= 2:
                d=self.target; self.state=d+'_GREEN'; self.elapsed=0; self.q[d]=0; self.e[d]=False; self.target=None
            return
        cur=self.state[:2]; other='EW' if cur=='NS' else 'NS'
        if self.e[other]: self.state='ALL_RED'; self.target=other; self.elapsed=0; return
        if self.elapsed >= 30 and self.q[other] > 0: self.state='ALL_RED'; self.target=other; self.elapsed=0; return
        if self.elapsed >= 10 and self.q[other] >= self.q[cur] + 3: self.state='ALL_RED'; self.target=other; self.elapsed=0
    def snapshot(self):
        return {'state':self.state,'elapsed':self.elapsed,'ns_queue':self.q['NS'],'ew_queue':self.q['EW'],'ns_emergency':self.e['NS'],'ew_emergency':self.e['EW']}
