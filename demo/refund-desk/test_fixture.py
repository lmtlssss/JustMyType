"""Fixed, hand-calculated policy cases. No model output in this scorer."""
import copy
from fixture import generate,oracle
CASES = {4101: ('refund', 4620), 4107: ('refund', 11220), 4113: ('refund', 3620), 4114: ('refund', 6580), 4115: ('deny', 0), 4117: ('deny', 0), 4119: ('refund', 5520), 4120: ('deny', 0), 4121: ('refund', 11990), 4122: ('deny', 0), 4123: ('review', 0), 4126: ('refund', 8580), 4127: ('deny', 0), 4132: ('refund', 8580), 4133: ('deny', 0), 4134: ('deny', 0), 4137: ('review', 0), 4143: ('review', 0), 4145: ('review', 0), 4146: ('review', 0), 4147: ('refund', 25000), 4148: ('review', 0)}
def test_fixed_cases():
    records={r['request_id']:r for r in generate()}
    for number,expected in CASES.items():
        result=oracle(records['R-'+str(number)])
        assert (result['decision'],result['amount_cents'])==expected
def test_deterministic_and_immutable():
    records=generate();before=copy.deepcopy(records)
    for record in records: oracle(record)
    assert records==before==generate()
    assert len({r['request_id'] for r in records})==48
def test_limit_and_shipping():
    records={r['request_id']:r for r in generate()}
    row=copy.deepcopy(records['R-4147']);row['lines'][0]['unit_tax_paid_cents']+=1;row['captured_cents']+=1
    assert oracle(row)['decision']=='review'
    row=copy.deepcopy(records['R-4119']);row['prior_shipping_refunded']=True
    assert oracle(row)['amount_cents']==4620
