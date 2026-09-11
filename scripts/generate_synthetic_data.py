#!/usr/bin/env python3
"""Deterministic synthetic operational world generator for FORTIFY Phase 1."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
import pandas as pd

SCENARIOS = ("STABLE", "HIGH_LOAD", "RECOVERY_DEFICIT", "PROLONGED_DEPLOYMENT", "VOLATILE", "RECOVERY_AFTER_PEAK")
UNIT_TYPES = ("FIELD", "BORDER", "HIGH_INTENSITY", "URBAN", "TRAINING", "LOGISTICS")
ROLES = ("OPERATIONS", "PATROL", "LOGISTICS", "COMMUNICATIONS", "MEDICAL_SUPPORT", "ADMINISTRATION", "TRAINING")
DUTY_TYPES = ("DAY", "NIGHT", "EMERGENCY", "PATROL", "ADMIN", "TRAINING_SUPPORT")
LEAVE_TYPES = ("ANNUAL", "CASUAL", "SPECIAL", "REST")
TRAINING_TYPES = ("TACTICAL", "FITNESS", "PROCEDURAL", "SKILL", "REFRESHER")
INCIDENT_TYPES = ("ROUTINE_OPERATION", "HIGH_INTENSITY_OPERATION", "EMERGENCY_RESPONSE", "EXTENDED_OPERATION")
LOCATION_BY_UNIT = {"FIELD":"REMOTE_FIELD", "BORDER":"BORDER_ZONE", "HIGH_INTENSITY":"HIGH_INTENSITY_SECTOR", "URBAN":"URBAN_AREA", "TRAINING":"TRAINING_AREA", "LOGISTICS":"LOGISTICS_HUB"}
UNIT_PROFILE = {
    "FIELD": (0.18, 8.5, 3.0, 0.035, 0.55, 0.05),
    "BORDER": (0.34, 9.0, 3.2, 0.040, 0.60, 0.04),
    "HIGH_INTENSITY": (0.25, 9.5, 3.6, 0.075, 0.65, 0.045),
    "URBAN": (0.22, 8.0, 2.8, 0.045, 0.45, 0.05),
    "TRAINING": (0.08, 7.5, 2.7, 0.018, 0.28, 0.22),
    "LOGISTICS": (0.12, 8.0, 2.5, 0.020, 0.35, 0.08),
}
DUTY_BOUNDS = (4.0, 14.0)
REST_BOUNDS = (4.0, 14.0)
LEAVE_BOUNDS = (3, 14)
TRAINING_BOUNDS = (2.0, 8.0)

@dataclass(frozen=True)
class Config:
    personnel: int = 500
    days: int = 180
    seed: int = 42
    output: Path = Path("data/generated")
    start_date: str = "2026-01-01"
    wellness_coverage: float = 0.35

@dataclass(frozen=True)
class Person:
    person_id: str
    unit_id: str
    role: str
    unit_type: str
    scenario: str
    service_years: int
    joining_date: str
    posting_start: str


def choice(rng: np.random.Generator, vals, probs):
    return str(rng.choice(list(vals), p=np.asarray(probs, dtype=float) / np.sum(probs)))


def nfloat(rng, mean, sd, lo, hi):
    return round(float(np.clip(rng.normal(mean, sd), lo, hi)), 2)


def dstr(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def units_frame():
    assumptions = {
        "FIELD":"Higher deployment intensity",
        "BORDER":"Higher night-duty probability",
        "HIGH_INTENSITY":"Higher incident/workload probability",
        "URBAN":"More variable schedules",
        "TRAINING":"Higher scheduled training load",
        "LOGISTICS":"Different duty and support patterns",
    }
    rows=[]
    for i, unit_type in enumerate(UNIT_TYPES, 1):
        night, hrs, inten, inc, dep, tr = UNIT_PROFILE[unit_type]
        for v in range(1,4):
            rows.append({
                "unit_id":f"U-{i:02d}{v}", "unit_type":unit_type,
                "unit_name":f"Synthetic {unit_type.replace('_',' ').title()} Unit {v}",
                "night_duty_probability":night, "typical_duty_hours":hrs,
                "typical_intensity_level":inten, "incident_probability":inc,
                "deployment_probability":dep, "training_probability":tr,
                "operational_assumption":assumptions[unit_type],
            })
    return pd.DataFrame(rows)


def scenario_params(s, day_i, days):
    if s == "STABLE": return 0.00, 0.00, 0.0, 0.05
    if s == "HIGH_LOAD": return 0.22, 0.09, -0.8, 0.08
    if s == "RECOVERY_DEFICIT": return 0.14, 0.06, -1.7, 0.05
    if s == "PROLONGED_DEPLOYMENT": return 0.18, 0.07, -1.0, 0.04
    if s == "VOLATILE": return 0.17*math.sin(day_i/4), 0.11, -0.6, 0.22
    peak = max(1, int(days*0.55))
    return ((0.23,0.08,-1.0,0.08) if day_i <= peak else (-0.08,-0.02,1.3,0.08))


def make_people(cfg, units, rng):
    start=pd.Timestamp(cfg.start_date)
    scenarios=[SCENARIOS[i%len(SCENARIOS)] for i in range(cfg.personnel)]
    rng.shuffle(scenarios)
    u=units.to_dict("records")
    rows=[]; people=[]
    for i in range(1,cfg.personnel+1):
        unit=u[int(rng.integers(len(u)))]
        role=str(rng.choice(ROLES))
        yrs=int(rng.integers(1,26))
        join=start-pd.Timedelta(days=int(yrs*365+rng.integers(0,365)))
        post=start-pd.Timedelta(days=int(rng.integers(0,270)))
        pid=f"P-{i:04d}"
        rows.append({"person_id":pid,"unit_id":unit["unit_id"],"role":role,"deployment_type":unit["unit_type"],"service_years":yrs,"joining_date":dstr(join),"current_posting_start":dstr(post)})
        people.append(Person(pid,unit["unit_id"],role,unit["unit_type"],scenarios[i-1],yrs,dstr(join),dstr(post)))
    return pd.DataFrame(rows), people


def deployment_plan(p, cfg, rng, start, end):
    _,_,_,_,base,_=UNIT_PROFILE[p.unit_type]
    if p.scenario=="PROLONGED_DEPLOYMENT": base=min(0.95,base+0.25)
    if rng.random()>base: return []
    count=2 if p.scenario in {"VOLATILE","STABLE","RECOVERY_AFTER_PEAK"} and rng.random()<0.22 else 1
    out=[]; cursor=start+pd.Timedelta(days=int(rng.integers(3,20)))
    for n in range(count):
        if cursor>end-pd.Timedelta(days=10): break
        if p.scenario=="PROLONGED_DEPLOYMENT": dur=int(rng.integers(75,136))
        elif p.scenario=="HIGH_LOAD": dur=int(rng.integers(55,106))
        elif p.scenario=="RECOVERY_DEFICIT": dur=int(rng.integers(45,86))
        elif p.scenario=="RECOVERY_AFTER_PEAK": dur=int(rng.integers(35,76))
        else: dur=int(rng.integers(25,71))
        ds=cursor; de=min(end,ds+pd.Timedelta(days=dur-1))
        _,_,mean_int,_,_,_=UNIT_PROFILE[p.unit_type]
        out.append({"deployment_event_id":f"DEP-{p.person_id[2:]}-{n+1:02d}","person_id":p.person_id,"deployment_type":p.unit_type,"start_date":dstr(ds),"end_date":dstr(de),"intensity_level":int(np.clip(round(mean_int+rng.integers(-1,2)),1,5)),"location_type":LOCATION_BY_UNIT[p.unit_type]})
        cursor=de+pd.Timedelta(days=int(rng.integers(12,35)))
    return out


def leave_plan(p,cfg,rng,start,end):
    count=int(rng.integers(1,4))
    if p.scenario=="PROLONGED_DEPLOYMENT": count=1
    elif p.scenario=="HIGH_LOAD": count=int(rng.integers(1,3))
    elif p.scenario=="RECOVERY_AFTER_PEAK": count=int(rng.integers(2,4))
    out=[]; cursor=start+pd.Timedelta(days=int(rng.integers(5, min(40, max(6, cfg.days//3+5)))))
    for i in range(count):
        if cursor>end-pd.Timedelta(days=2): break
        max_len=max(1, min(LEAVE_BOUNDS[1], (end-cursor).days+1))
        min_len=min(LEAVE_BOUNDS[0], max_len)
        length=int(rng.integers(min_len, max_len+1))
        ls=cursor; le=min(end,ls+pd.Timedelta(days=length-1))
        out.append({"leave_event_id":f"LV-{p.person_id[2:]}-{i+1:02d}","person_id":p.person_id,"start_date":dstr(ls),"end_date":dstr(le),"duration_days":int((le-ls).days+1),"leave_type":choice(rng,LEAVE_TYPES,[.55,.15,.10,.20]),"status":choice(rng,("APPROVED","COMPLETED"),[.72,.28])})
        cursor=le+pd.Timedelta(days=int(rng.integers(25,60)))
    return out


def active_id(day, plans):
    s=dstr(day)
    for x in plans:
        if x["start_date"]<=s<=x["end_date"]: return x["deployment_event_id"]
    return ""


def on_leave(day, leaves):
    s=dstr(day)
    return any(x["start_date"]<=s<=x["end_date"] for x in leaves)


def duty_type(p,night,high,rng,training):
    if training: return "TRAINING_SUPPORT"
    if high and rng.random()<.28: return "EMERGENCY"
    if night: return choice(rng,("NIGHT","PATROL","EMERGENCY"),[.65,.27,.08])
    if p.role=="PATROL": return choice(rng,("PATROL","DAY","EMERGENCY"),[.55,.35,.10])
    if p.role=="ADMINISTRATION": return choice(rng,("ADMIN","DAY","TRAINING_SUPPORT"),[.65,.25,.10])
    return choice(rng,("DAY","PATROL","ADMIN","TRAINING_SUPPORT"),[.50,.25,.17,.08])


def wellness_row(p, day, day_i, days, duty_hours, rest_hours, training_hours, incidents, rng):
    pressure=.55*max(0,duty_hours-8)+.75*max(0,8-rest_hours)+.6*training_hours+.9*incidents
    if p.scenario=="RECOVERY_AFTER_PEAK": pressure += -1.0 if day_i>days//2 else .7
    if p.scenario=="STABLE": pressure -= .4
    pressure=max(0,pressure+float(rng.normal(0,.65)))
    ps=int(np.clip(round(2.1+pressure*.45),1,5))
    sleep=int(np.clip(round(4-max(0,8-rest_hours)*.28-incidents*.15+rng.normal(0,.45)),1,5))
    energy=int(np.clip(round(4-pressure*.35+rng.normal(0,.5)),1,5))
    mood=int(np.clip(round(4-pressure*.25+rng.normal(0,.55)),1,5))
    manage=int(np.clip(round(4-pressure*.30+rng.normal(0,.5)),1,5))
    support=bool(ps>=4 and rng.random()<.12)
    return {"wellness_event_id":f"WEL-{p.person_id[2:]}-{day_i+1:03d}","person_id":p.person_id,"date":dstr(day),"mood_score":mood,"energy_score":energy,"sleep_quality":sleep,"perceived_stress":ps,"workload_manageability":manage,"support_request":support}


def generate(cfg: Config):
    if cfg.personnel<=0 or cfg.days<=0: raise ValueError("personnel and days must be positive")
    if not 0<cfg.wellness_coverage<=1: raise ValueError("wellness_coverage must be in (0,1]")
    start=pd.Timestamp(cfg.start_date); end=start+pd.Timedelta(days=cfg.days-1); rng=np.random.default_rng(cfg.seed)
    units=units_frame(); personnel, people=make_people(cfg,units,rng)
    dep=[]; leaves=[]; duty=[]; recovery=[]; training=[]; incident=[]; wellness=[]
    wellness_people={p.person_id for p in people if rng.random()<cfg.wellness_coverage}
    for p in people:
        deps=deployment_plan(p,cfg,rng,start,end); dep += deps
        lvs=leave_plan(p,cfg,rng,start,end); leaves += lvs
        _,base_hours,base_int,base_inc,_,train_prob=UNIT_PROFILE[p.unit_type]
        prev_hours=base_hours; prev_night=False; consec=0; prev_inc=0
        for di in range(cfg.days):
            day=start+pd.Timedelta(days=di)
            load,night_adj,recovery_adj,vol=scenario_params(p.scenario,di,cfg.days)
            dep_id=active_id(day,deps); leave=on_leave(day,lvs)
            tp=train_prob + (0.04 if p.scenario=="HIGH_LOAD" else 0) + (0.03 if p.scenario=="RECOVERY_AFTER_PEAK" and di<cfg.days//2 else 0)
            training_today=not leave and rng.random()<min(tp,.5)
            tr_hours=0.0
            if training_today:
                tr_hours=nfloat(rng,4.5+load*2,1.1,*TRAINING_BOUNDS)
                tr_int=int(np.clip(round(rng.normal(3+load*3,.9)),1,5))
                training.append({"training_event_id":f"TRN-{p.person_id[2:]}-{di+1:03d}","person_id":p.person_id,"date":dstr(day),"duration_hours":tr_hours,"training_type":choice(rng,TRAINING_TYPES,[.28,.20,.18,.24,.10]),"intensity_level":tr_int})
            if leave:
                rest=nfloat(rng,12,1.1,*REST_BOUNDS)
                recovery.append({"recovery_event_id":f"REC-{p.person_id[2:]}-{di+1:03d}","person_id":p.person_id,"date":dstr(day),"rest_duration_hours":rest})
                prev_hours=0; prev_night=False; consec=0; prev_inc=0
                if p.person_id in wellness_people and rng.random()<.16: wellness.append(wellness_row(p,day,di,cfg.days,0,rest,0,0,rng))
                continue
            npb=float(UNIT_PROFILE[p.unit_type][0])+night_adj
            if p.scenario=="VOLATILE" and di%3==0: npb+=.16
            night=bool(rng.random()<np.clip(npb,.03,.65))
            high=bool(rng.random()<np.clip(base_inc*3+max(load,0)*.4,.05,.45))
            dtype=duty_type(p,night,high,rng,training_today)
            mean=base_hours+load*8 + (0.35*int(rng.integers(1,4)) if dep_id else 0) + (1.3 if high else 0) + (.4 if training_today else 0)
            if p.scenario=="VOLATILE": mean+=float(rng.normal(0,1.2))
            if prev_night and p.scenario=="RECOVERY_DEFICIT": mean+=.5
            hrs=nfloat(rng,mean,1.25+vol*2,*DUTY_BOUNDS)
            inten=int(np.clip(round(base_int+load*6+rng.normal(0,.7)+(1 if high else 0)),1,5))
            duty.append({"duty_event_id":f"DUT-{p.person_id[2:]}-{di+1:03d}","person_id":p.person_id,"timestamp":(day+pd.Timedelta(hours=21 if night else int(rng.integers(5,14)))).isoformat(),"date":dstr(day),"duty_type":dtype,"duration_hours":hrs,"night_shift":night,"intensity_level":inten,"deployment_id":dep_id})
            consec+=1
            rest_mean=11.8-min(3,prev_hours*.25)-(1 if prev_night else 0)-min(1.5,max(0,consec-2)*.30)+recovery_adj-(.4 if dep_id else 0)-(.6 if prev_inc else 0)
            rest=nfloat(rng,rest_mean,1+vol*1.4,*REST_BOUNDS)
            recovery.append({"recovery_event_id":f"REC-{p.person_id[2:]}-{di+1:03d}","person_id":p.person_id,"date":dstr(day),"rest_duration_hours":rest})
            ip=base_inc+(.012 if dep_id else 0)+(.018 if p.scenario=="HIGH_LOAD" else 0)+(.012 if p.scenario=="RECOVERY_AFTER_PEAK" and di<=cfg.days//2 else 0)+(.04 if high else 0)
            incflag=False
            if rng.random()<np.clip(ip,.005,.18):
                incflag=True
                itype=choice(rng,INCIDENT_TYPES,[.55,.25,.12,.08] if inten<4 else [.25,.35,.25,.15])
                ii=int(np.clip(round(rng.normal(max(2,inten),.8)),1,5))
                req=round(float(np.clip(2+ii*.8+rng.normal(0,.6),1,8)),2)
                incident.append({"incident_event_id":f"INC-{p.person_id[2:]}-{di+1:03d}","person_id":p.person_id,"date":dstr(day),"incident_type":itype,"intensity_level":ii,"recovery_requirement":req})
            prev_inc=int(incflag); prev_hours=hrs; prev_night=night
            if p.person_id in wellness_people and rng.random()<.23: wellness.append(wellness_row(p,day,di,cfg.days,hrs,rest,tr_hours,int(incflag),rng))
    columns={
        "personnel.csv":["person_id","unit_id","role","deployment_type","service_years","joining_date","current_posting_start"],
        "units.csv":["unit_id","unit_type","unit_name","night_duty_probability","typical_duty_hours","typical_intensity_level","incident_probability","deployment_probability","training_probability","operational_assumption"],
        "duty_events.csv":["duty_event_id","person_id","timestamp","date","duty_type","duration_hours","night_shift","intensity_level","deployment_id"],
        "recovery_events.csv":["recovery_event_id","person_id","date","rest_duration_hours"],
        "leave_events.csv":["leave_event_id","person_id","start_date","end_date","duration_days","leave_type","status"],
        "deployment_events.csv":["deployment_event_id","person_id","deployment_type","start_date","end_date","intensity_level","location_type"],
        "training_events.csv":["training_event_id","person_id","date","duration_hours","training_type","intensity_level"],
        "incident_events.csv":["incident_event_id","person_id","date","incident_type","intensity_level","recovery_requirement"],
        "wellness_events.csv":["wellness_event_id","person_id","date","mood_score","energy_score","sleep_quality","perceived_stress","workload_manageability","support_request"],
    }
    raw={"personnel.csv":personnel,"units.csv":units,"duty_events.csv":pd.DataFrame(duty),"recovery_events.csv":pd.DataFrame(recovery),"leave_events.csv":pd.DataFrame(leaves),"deployment_events.csv":pd.DataFrame(dep),"training_events.csv":pd.DataFrame(training),"incident_events.csv":pd.DataFrame(incident),"wellness_events.csv":pd.DataFrame(wellness)}
    return {name: df.reindex(columns=columns[name]) for name,df in raw.items()}


def scenario_counts(personnel: int, seed: int) -> dict[str, int]:
    rng=np.random.default_rng(seed)
    values=[SCENARIOS[i%len(SCENARIOS)] for i in range(personnel)]
    rng.shuffle(values)
    return {s: values.count(s) for s in SCENARIOS}

def write_readme(out: Path, cfg: Config, frames: dict[str, pd.DataFrame]) -> None:
    counts=scenario_counts(cfg.personnel,cfg.seed)
    text=f"""# FORTIFY Phase 1 — Generated Synthetic Operational World

All files in this directory are **synthetic prototype data** generated for FORTIFY Phase 1. They are not real government personnel records, not classified operational information, and not clinically validated data.

## Generation parameters

- Personnel: {cfg.personnel}
- Simulation days per personnel: {cfg.days}
- Start date: {cfg.start_date}
- Seed: {cfg.seed}
- Optional wellness personnel target: {cfg.wellness_coverage:.2f}

## Scenario archetypes

Scenario archetypes are generator-internal controls used to create varied operational trajectories. They are **not clinical labels, ground truth stress labels, or model targets**, and no scenario column is written to the event datasets.

- STABLE: normal workload and recovery
- HIGH_LOAD: sustained higher operational workload
- RECOVERY_DEFICIT: repeated shorter recovery periods
- PROLONGED_DEPLOYMENT: longer deployment periods with reduced leave opportunities
- VOLATILE: irregular duty and schedule changes
- RECOVERY_AFTER_PEAK: temporary high load followed by easing recovery conditions

Generation-only scenario allocation: {counts}

## Output files

- `personnel.csv` — synthetic personnel master records
- `units.csv` — synthetic unit types and generator assumptions
- `duty_events.csv` — longitudinal duty events
- `recovery_events.csv` — daily rest/recovery events
- `leave_events.csv` — leave intervals
- `deployment_events.csv` — deployment intervals
- `training_events.csv` — training events
- `incident_events.csv` — synthetic operational incidents
- `wellness_events.csv` — sparse, optional voluntary self-report observations

Formal schemas are under `../schemas/`.

## Temporal behavior

Events are generated as sequences rather than independent random rows. Leave suppresses ordinary duty on affected dates; deployment status affects duty generation; prior duty duration and night duty influence subsequent recovery; training adds workload to the day; incidents create additional recovery requirements; and scenario controls vary these operational relationships over time.

## Limitations

This is a demonstration-oriented synthetic world. Unit characteristics, duty distributions, incident types, and wellness observations are synthetic assumptions intended to provide realistic-looking longitudinal relationships. They are not estimates of actual CRPF, Armed Forces, CAPF, police, or any other organization's operational distributions.

The `perceived_stress` field is an optional synthetic self-report and must not be interpreted as a clinical diagnosis. Missing wellness observations are expected and are not treated as evidence of elevated risk.

## Validation

Run from the repository root:

```bash
python scripts/validate_synthetic_data.py --output data/generated --personnel {cfg.personnel} --days {cfg.days}
```

"""
    (out/"README.md").write_text(text,encoding="utf-8")

def write(frames, out):
    out.mkdir(parents=True,exist_ok=True)
    for f in out.glob("*.csv"): f.unlink()
    for name,df in frames.items(): df.to_csv(out/name,index=False,lineterminator="\n")


def main():
    ap=argparse.ArgumentParser(description="Generate FORTIFY Phase 1 synthetic operational world")
    ap.add_argument("--personnel",type=int,default=500); ap.add_argument("--days",type=int,default=180); ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--output",type=Path,default=Path("data/generated")); ap.add_argument("--start-date",default="2026-01-01")
    ap.add_argument("--wellness-coverage",type=float,default=.35)
    a=ap.parse_args(); cfg=Config(a.personnel,a.days,a.seed,a.output,a.start_date,a.wellness_coverage)
    frames=generate(cfg); write(frames,cfg.output)
    for n in frames: print(f"{n.replace('.csv','').replace('_',' ').title()}: {len(frames[n])}")
    write_readme(cfg.output,cfg,frames)
    print("Scenario mix (generation-only): " + ", ".join(f"{k}={v}" for k,v in scenario_counts(cfg.personnel,cfg.seed).items()))
    print(f"Simulation horizon: {cfg.days} days starting {cfg.start_date}")
    print(f"Seed: {cfg.seed}")
    print(f"Output: {cfg.output}")

if __name__=="__main__": main()
