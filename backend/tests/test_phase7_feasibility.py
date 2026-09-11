from __future__ import annotations

import pandas as pd

from backend.app.ml.feasibility_config import FeasibilityPolicyConfig
from backend.app.ml.feasibility_engineering import build_intervention_feasibility, validate_feasibility_output


def intervention(action="RECOVERY_SUPPORT", band="MODERATE"):
    return pd.DataFrame([{"person_id":"P-1","date":"2026-01-10","risk_band":band,"recommended_action":action,"priority":"MEDIUM" if band=="MODERATE" else "HIGH","requires_human_review":True,"model_version":"phase5-v1","policy_version":"phase6-v1"}])

def base_inputs(duty_hours=0, rest=8, leave=False, deployed=False, training=False):
    personnel=pd.DataFrame([{"person_id":"P-1","unit_id":"U-1","role":"OPERATIONS","deployment_type":"FIELD"}])
    duty=pd.DataFrame([{ "duty_event_id":"D1","person_id":"P-1","date":"2026-01-10","duration_hours":duty_hours}] if duty_hours else columns_duty())
    recovery=pd.DataFrame([{ "recovery_event_id":"R1","person_id":"P-1","date":"2026-01-10","rest_duration_hours":rest}])
    leave_df=pd.DataFrame([{ "leave_event_id":"L1","person_id":"P-1","start_date":"2026-01-10","end_date":"2026-01-12","duration_days":3,"leave_type":"REGULAR","status":"APPROVED"}] if leave else columns_leave())
    dep_df=pd.DataFrame([{ "deployment_event_id":"DEP1","person_id":"P-1","deployment_type":"FIELD","start_date":"2026-01-09","end_date":"2026-01-12","intensity_level":4,"location_type":"FIELD"}] if deployed else columns_dep())
    train_df=pd.DataFrame([{ "training_event_id":"T1","person_id":"P-1","date":"2026-01-10","duration_hours":4,"training_type":"TACTICAL","intensity_level":3}] if training else columns_train())
    return personnel,duty,recovery,leave_df,dep_df,train_df

def columns_duty(): return pd.DataFrame(columns=["duty_event_id","person_id","date","duration_hours"])
def columns_leave(): return pd.DataFrame(columns=["leave_event_id","person_id","start_date","end_date","duration_days","leave_type","status"])
def columns_dep(): return pd.DataFrame(columns=["deployment_event_id","person_id","deployment_type","start_date","end_date","intensity_level","location_type"])
def columns_train(): return pd.DataFrame(columns=["training_event_id","person_id","date","duration_hours","training_type","intensity_level"])

def build(inter, vals): return build_intervention_feasibility(inter, *vals)

def test_feasible_state():
    out=build(intervention("ROUTINE_MONITORING","LOW"), base_inputs()); assert out.loc[0,"feasibility_status"]=="FEASIBLE"

def test_adjustment_on_duty_conflict():
    out=build(intervention(), base_inputs(duty_hours=4)); assert out.loc[0,"feasibility_status"] in {"FEASIBLE_WITH_ADJUSTMENT","CONSTRAINED"}; assert "active_duty_conflict" in out.loc[0,"constraint_flags"]

def test_recovery_constraint():
    out=build(intervention(), base_inputs(rest=5)); assert out.loc[0,"feasibility_status"] in {"FEASIBLE_WITH_ADJUSTMENT","CONSTRAINED"}

def test_leave_and_deployment_conflicts():
    out=build(intervention("PRIORITY_WELFARE_REVIEW","HIGH"), base_inputs(duty_hours=11, rest=5, leave=True, deployed=True)); assert out.loc[0,"feasibility_status"] in {"CONSTRAINED","NOT_FEASIBLE"}; assert "leave_conflict" in out.loc[0,"constraint_flags"]; assert "active_deployment" in out.loc[0,"constraint_flags"]

def test_not_feasible_multiple_hard_constraints():
    out=build(intervention("PRIORITY_WELFARE_REVIEW","HIGH"), base_inputs(duty_hours=15, rest=3, leave=True)); assert out.loc[0,"feasibility_status"]=="NOT_FEASIBLE"; assert bool(out.loc[0,"requires_human_review"]) is True

def test_missing_optional_context():
    out=build(intervention(), base_inputs()); assert isinstance(out.loc[0,"feasibility_rationale"], str)

def test_deterministic_and_schema():
    vals=base_inputs(duty_hours=6, rest=7, training=True)
    a=build(intervention(), vals); b=build(intervention(), vals); pd.testing.assert_frame_equal(a,b); validate_feasibility_output(a)

def test_future_events_do_not_change_date_t():
    vals=base_inputs(duty_hours=5, rest=7)
    a=build(intervention(), vals)
    personnel,duty,recovery,leave,dep,train=vals
    duty2=pd.concat([duty, pd.DataFrame([{ "duty_event_id":"FUT","person_id":"P-1","date":"2026-01-11","duration_hours":20}])],ignore_index=True)
    b=build(intervention(), (personnel,duty2,recovery,leave,dep,train))
    pd.testing.assert_frame_equal(a,b)

def test_safety_no_forbidden_fields():
    out=build(intervention(), base_inputs()); joined=" ".join(out.astype(str).stack().tolist()).lower();
    for term in ["depression","anxiety","ptsd","disciplinary","punishment","termination","performance rating"]: assert term not in joined
    for col in out.columns: assert "medical" not in col.lower()
