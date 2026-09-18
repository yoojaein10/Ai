import json

from sqlalchemy.orm import Session

from app.db.models import EvalSetting
from app.schemas.eval_setting import EvalSettingUpsert, GradeCriterion


def _deserialize(setting: EvalSetting) -> dict:
    return {
        "id": setting.id,
        "year": setting.year,
        "weight_config": json.loads(setting.weight_config) if setting.weight_config else {},
        "grade_criteria": [
            GradeCriterion(**c) for c in (json.loads(setting.grade_criteria) if setting.grade_criteria else [])
        ],
        "updated_at": setting.updated_at,
    }


def get_setting_by_year(db: Session, year: int) -> dict | None:
    setting = db.query(EvalSetting).filter(EvalSetting.year == year).first()
    if setting is None:
        return None
    return _deserialize(setting)


def upsert_setting(db: Session, data: EvalSettingUpsert) -> dict:
    setting = db.query(EvalSetting).filter(EvalSetting.year == data.year).first()
    weight_json = json.dumps(data.weight_config)
    criteria_json = json.dumps([c.model_dump() for c in data.grade_criteria])

    if setting is None:
        setting = EvalSetting(
            year=data.year,
            weight_config=weight_json,
            grade_criteria=criteria_json,
        )
        db.add(setting)
    else:
        setting.weight_config = weight_json
        setting.grade_criteria = criteria_json

    db.commit()
    db.refresh(setting)
    return _deserialize(setting)
