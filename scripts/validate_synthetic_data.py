#!/usr/bin/env python3
"""Validation/reporting for FORTIFY Phase 1 generated CSVs."""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

FILES=("personnel.csv","units.csv","duty_events.csv","recovery_events.csv","leave_events.csv","deployment_events.csv","training_events.csv","incident_events.csv","wellness_events.csv")
SETS={
"unit_type":{"FIELD","BORDER","HIGH_INTENSITY","URBAN","TRAINING","LOGISTICS"},
"role":{"OPERATIONS","PATROL","LOGISTICS","COMMUNICATIONS","MEDICAL_SUPPORT","ADMINISTRATION","TRAINING"},
"duty_type":{"DAY","NIGHT","EMERGENCY","PATROL","ADMIN","TRAINING_SUPPORT"},
"leave_type":{"ANNUAL","CASUAL","SPECIAL","REST"},"status":{"APPROVED","COMPLETED"},
"training_type":{"TACTICAL","FITNESS","PROCEDURAL","SKILL","REFRESHER"},
"incident_type":{"ROUTINE_OPERATION","HIGH_INTENSITY_OPERATION","EMERGENCY_RESPONSE","EXTENDED_OPERATION"},
"location_type":{"REMOTE_FIELD","BORDER_ZONE","HIGH_INTENSITY_SECTOR","URBAN_AREA","TRAINING_AREA","LOGISTICS_HUB"},
}

def validate(out:Path, personnel_n:int|None=None, days:int|None=None):
    errors=[]; frames={}
    def req(ok,msg):
        if not ok: errors.append(msg)
    for name in FILES:
        p=out/name; req(p.exists(),f"missing {name}")
        if p.exists(): frames[name]=pd.read_csv(p)
    if "personnel.csv" not in frames:return False,errors,frames
    pers=frames["personnel.csv"]; persons=set(pers.person_id.astype(str))
    req(len(persons)==len(pers),"duplicate person_id");
    if personnel_n is not None:req(len(pers)==personnel_n,f"expected {personnel_n} personnel, got {len(pers)}")
    units=frames.get("units.csv",pd.DataFrame()); unit_ids=set(units.get("unit_id",pd.Series(dtype=str)).astype(str))
    req(len(unit_ids)==len(units),"duplicate unit_id"); req(set(pers.unit_id.astype(str))<=unit_ids,"invalid personnel unit_id")
    req(set(units.get("unit_type",pd.Series(dtype=str)).astype(str))<=SETS["unit_type"],"invalid unit_type")
    for name,df in frames.items():
        req(len(df.iloc[:,0].astype(str))==df.iloc[:,0].astype(str).nunique(),f"duplicate ID in {name}")
        if "person_id" in df: req(set(df.person_id.astype(str))<=persons,f"orphan person_id in {name}")
        req(not ({"scenario","scenario_type","stress_score","mental_health_score","depression_label","anxiety_label","diagnosis"}&set(df.columns)),f"forbidden clinical/scenario field in {name}")
    duty=frames.get("duty_events.csv");
    if duty is not None and len(duty):
        req(duty.duration_hours.between(4,14).all(),"duty duration outside 4-14h")
        req(duty.intensity_level.isin([1,2,3,4,5]).all(),"invalid duty intensity")
        req(duty.duty_type.isin(SETS["duty_type"]).all(),"invalid duty_type")
        req(duty.night_shift.astype(bool).any(),"no night duty represented")
        req(pd.to_datetime(duty.date,errors="coerce").notna().all(),"invalid duty date")
        req(pd.to_datetime(duty.timestamp,errors="coerce").notna().all(),"invalid duty timestamp")
        if days is not None and len(duty): req((pd.to_datetime(duty.date).max()-pd.to_datetime(duty.date).min()).days<days,"duty exceeds horizon")
    rec=frames.get("recovery_events.csv");
    if rec is not None:req(rec.rest_duration_hours.between(4,14).all(),"rest duration outside 4-14h")
    leave=frames.get("leave_events.csv");
    if leave is not None and len(leave):
        s=pd.to_datetime(leave.start_date,errors="coerce");e=pd.to_datetime(leave.end_date,errors="coerce")
        req(s.notna().all() and e.notna().all(),"invalid leave date");req((s<=e).all(),"leave start_date > end_date");req(leave.duration_days.between(3,14).all(),"leave duration outside 3-14d")
        req(leave.leave_type.isin(SETS["leave_type"]).all(),"invalid leave_type");req(leave.status.isin(SETS["status"]).all(),"invalid leave status")
    dep=frames.get("deployment_events.csv");
    if dep is not None and len(dep):
        s=pd.to_datetime(dep.start_date,errors="coerce");e=pd.to_datetime(dep.end_date,errors="coerce")
        req(s.notna().all() and e.notna().all(),"invalid deployment date");req((s<=e).all(),"deployment start_date > end_date");req(dep.intensity_level.isin([1,2,3,4,5]).all(),"invalid deployment intensity");req(dep.deployment_type.isin(SETS["unit_type"]).all(),"invalid deployment_type");req(dep.location_type.isin(SETS["location_type"]).all(),"invalid location_type")
    tr=frames.get("training_events.csv");
    if tr is not None and len(tr):req(tr.duration_hours.between(2,8).all(),"training duration outside 2-8h");req(tr.intensity_level.isin([1,2,3,4,5]).all(),"invalid training intensity");req(tr.training_type.isin(SETS["training_type"]).all(),"invalid training_type")
    inc=frames.get("incident_events.csv");
    if inc is not None and len(inc):req(inc.intensity_level.isin([1,2,3,4,5]).all(),"invalid incident intensity");req(inc.recovery_requirement.between(1,8).all(),"invalid recovery requirement");req(inc.incident_type.isin(SETS["incident_type"]).all(),"invalid incident_type")
    wel=frames.get("wellness_events.csv");
    if wel is not None and len(wel):
        for c in ("mood_score","energy_score","sleep_quality","perceived_stress","workload_manageability"):req(wel[c].between(1,5).all(),f"{c} outside 1-5")
        req(wel.person_id.nunique()/max(1,len(persons))<.80,"wellness coverage too universal")
    req(duty is not None and duty.duty_type.nunique()>=4,"insufficient duty variety")
    # Every non-empty event table with person_id has a valid FK; deployment_id is either blank or valid.
    if duty is not None:
        dep_ids=set(dep.deployment_event_id.astype(str)) if dep is not None else set()
        nonblank=set(duty["deployment_id"].fillna("").astype(str)); nonblank.discard(""); nonblank.discard("nan"); req(nonblank<=dep_ids,"orphan deployment_id in duty_events")
        req(set(duty.person_id.astype(str))==persons,"not every personnel record has a duty history")
    if rec is not None:
        req(set(rec.person_id.astype(str))==persons,"not every personnel record has a recovery history")
    # Ensure the operational world contains multiple qualitative patterns through scenario-internal generation proxies.
    if duty is not None and len(duty):
        person_duty=duty.groupby("person_id")["duration_hours"].mean()
        req(person_duty.max()-person_duty.min()>1.0,"operational variability too narrow")
    counts={k:len(v) for k,v in frames.items()}
    return not errors,errors,counts

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=Path("data/generated"));p.add_argument("--personnel",type=int);p.add_argument("--days",type=int);a=p.parse_args()
    ok,errors,counts=validate(a.output,a.personnel,a.days)
    [print(f"{k}: {v}") for k,v in counts.items()]
    if errors:
        print("VALIDATION FAILED");[print(f"- {e}") for e in errors];raise SystemExit(1)
    print("VALIDATION PASSED")
if __name__=="__main__":main()
