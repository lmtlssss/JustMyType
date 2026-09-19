import importlib.util, tempfile, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("decisions",Path(__file__).parents[1]/"plugins/justmytype/scripts/decisions.py"); d=importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
class DecisionTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.q={"c":{"type":"choice","instructions":"pick","criteria":{"a":"Alpha","b":"Beta"}},"n":{"type":"noul","instructions":"judge"},"s":{"type":"score","instructions":"rate","criteria":["unrelated","useful","essential"]}}; self.p={"state":"x","questions":self.q}
 def tearDown(self): self.t.cleanup()
 def response(self,s,q): return {"model":"m","answers":{"c":{"type":"choice","choice":"a","probabilities":{"a":.9,"b":.1},"confidence":.8},"n":{"type":"noul","noul":.9},"s":{"type":"score","score":1.7,"probabilities":{"0":.1,"1":.1,"2":.8},"legend":{"0":"unrelated","1":"useful","2":"essential"},"confidence":.7}},"usage":{"input_tokens":1,"output_tokens":2}}
 def test_types_one_call_and_cache(self):
  calls=[]; fn=lambda s,q:(calls.append(1) or self.response(s,q)); p=dict(self.p,cache={"namespace":"n","generation":"1"}); self.assertEqual(d.evaluate(p,request=fn,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"ok"); self.assertTrue(d.evaluate(p,request=fn,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["cache_hit"]); self.assertEqual(len(calls),1)
 def test_invalid_cloud_off_and_redaction(self):
  bad=lambda s,q: {"model":"bad"}; self.assertEqual(d.evaluate(self.p,request=bad,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"unassessed"); self.assertEqual(d.evaluate(self.p,request=bad,redact=lambda x:{"secret":"x"},directory=self.t.name,enabled=True,model="m",engine_sha256="e")["evaluations"],0); self.assertEqual(d.evaluate(self.p,request=bad,redact=lambda x:x,directory=self.t.name,enabled=False,model="m",engine_sha256="e")["reason_codes"],["cloud_disabled"])
 def test_structured_and_invalid_questions(self):
  p=dict(self.p); p["questions"]=dict(self.q,c={"type":"choice","instructions":{"pick":["one"]},"criteria":{"a":None,"b":["Beta"]}})
  self.assertEqual(d.evaluate(p,request=self.response,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"ok")
  bad=dict(self.p); bad["questions"]=dict(self.q,n={"type":"noul","instructions":"x","criteria":{"yes":"Y"}})
  self.assertEqual(d.evaluate(bad,request=lambda s,q:self.fail("request"),redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"unassessed")
 def test_score_negative_and_bad_responses(self):
  def negative(s,q):
   r=self.response(s,q); r["answers"]["s"]["score"]=-1; return r
  self.assertEqual(d.evaluate(self.p,request=negative,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"unassessed")
  def missing(s,q): return {"model":"m","answers":{},"usage":{"input_tokens":1,"output_tokens":1}}
  self.assertEqual(d.evaluate(self.p,request=missing,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")["status"],"unassessed")
 def test_network_error_counts(self):
  def fail(s,q): raise RuntimeError("provider")
  d.evaluate(self.p,request=fail,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")
  self.assertEqual(d.stats(self.t.name)["evaluations"],1); self.assertEqual(d.stats(self.t.name)["errors"],1)

 def test_reported_score_uses_provider_precision(self):
  # Actual Jev response: rounded probabilities do not recover the precise score.
  levels=["Unrelated","Tangential","Useful background","Directly useful","Essential reference"]
  p={"state":"Find deployment instructions","questions":{"deploy":{"type":"score","instructions":"Rate relevance","criteria":levels}}}
  raw={"model":"m","answers":{"deploy":{"type":"score","score":3.78,"confidence":.82,"legend":{str(i):v for i,v in enumerate(levels)},"probabilities":{"0":0.0,"1":0.0,"2":0.0,"3":.2,"4":.8}}},"usage":{"input_tokens":477,"output_tokens":30}}
  out=d.evaluate(p,request=lambda s,q:raw,redact=lambda x:x,directory=self.t.name,enabled=True,model="m",engine_sha256="e")
  self.assertEqual(out["status"],"ok")
  self.assertEqual(out["answers"]["deploy"]["score"],3.78)
