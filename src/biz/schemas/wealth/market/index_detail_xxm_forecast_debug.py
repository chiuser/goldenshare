from typing import Literal

from pydantic import Field, model_validator

from .index_detail_xxm_forecast import (
    Dto, ForecastConditionDto, ForecastReferencesDto, ForecastResponseDto, NearestDecisionDto,
    PrecisionRangeDto, StructureFollowConditionDto, _validate_details,
)


class ForecastDebugDto(Dto):
    sourceInputId: str | None = Field(min_length=1)
    calendarInputId: str | None = Field(min_length=1)
    precisionPolicy: Literal["rounded3_guarded", "full_float"]
    references: ForecastReferencesDto
    selectedReference: Literal["NEAR", "FAR"] | None
    nearestDecision: NearestDecisionDto
    farEvaluated: bool
    conditions: list[ForecastConditionDto]
    precisionRanges: list[PrecisionRangeDto]
    structureFollowConditions: list[StructureFollowConditionDto]


class ForecastDebugResponseDto(ForecastResponseDto):
    debug: ForecastDebugDto

    @model_validator(mode="after")
    def complete_facts(self):
        native = self.debug.model_dump()
        for condition in native["structureFollowConditions"]:
            wave = condition["originWave"]
            wave["price_at"], wave["dif_at"] = wave.pop("priceAt"), wave.pop("difAt")
        _validate_details(self, self.debug, native=native)
        return self
