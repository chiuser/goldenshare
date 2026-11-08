import { assert, finite, keys, record, timeKey } from "../xxm/adapter";
import type { XxmReference, XxmWave, XxmDebugData } from "../xxm/types";
import type { DecodeXxmDebug } from "./types";
export function reference(raw: unknown, period: Parameters<DecodeXxmDebug>[1]["period"], through: string): XxmReference {
    keys(raw, "startTime endTime price dif priceAt difAt");
    for (const v of [raw.startTime, raw.endTime, raw.priceAt, raw.difAt])
        timeKey(v, period);
    assert(finite(raw.price) && raw.price > 0 && finite(raw.dif) && String(raw.startTime) <= String(raw.priceAt) && String(raw.priceAt) <= String(raw.endTime) && String(raw.startTime) <= String(raw.difAt) && String(raw.difAt) <= String(raw.endTime) && String(raw.endTime) <= through);
    return raw as unknown as XxmReference;
}
export function wave(raw: unknown, period: Parameters<DecodeXxmDebug>[1]["period"], through: string): XxmWave {
    keys(raw, "sign start end count price dif priceAt difAt");
    assert((raw.sign === 1 || raw.sign === -1) && Number.isInteger(raw.count) && Number(raw.count) > 0);
    reference({ startTime: raw.start, endTime: raw.end, price: raw.price, dif: raw.dif, priceAt: raw.priceAt, difAt: raw.difAt }, period, through);
    return raw as unknown as XxmWave;
}
const same = (a: unknown, b: unknown) => record(a) && record(b) && ["startTime", "endTime", "price", "dif", "priceAt", "difAt"].every(k => a[k] === b[k]);
export const decodeXxmDebug: DecodeXxmDebug = (raw, { response, period, check }) => {
    check();
    keys(raw, "sourceInputId points events structures");
    assert(typeof raw.sourceInputId === "string" && !!raw.sourceInputId && Array.isArray(raw.points) && Array.isArray(raw.events) && Array.isArray(raw.structures));
    const through = response.source.computedThrough;
    assert(raw.points.length === response.points.length && raw.events.length === response.events.length);
    const ids = new Set<string>();
    let previous = "";
    for (const s of raw.structures) {
        check();
        keys(s, "id direction structureEventId formedAt formationRoute originSegmentStart originalReference priceExtreme priceExtremeAt status originWave firstOppositeAt nextSameColorStart nextSameColorCount trackingPriceExtreme trackingPriceExtremeAt trackingEndedAt disappearedAt disappearanceReason");
        assert(through && typeof s.id === "string" && !!s.id && !ids.has(s.id) && typeof s.structureEventId === "string" && !!s.structureEventId && ["TOP", "BOTTOM"].includes(String(s.direction)) && ["dif_turn", "color_flip"].includes(String(s.formationRoute)) && ["ASSESSING", "FOLLOWING", "FINISHED", "DISAPPEARED"].includes(String(s.status)));
        ids.add(s.id);
        const order = String(s.formedAt) + s.id;
        assert(order >= previous);
        previous = order;
        assert(!response.events.some(e => e.id === s.id));
        for (const k of ["formedAt", "originSegmentStart", "priceExtremeAt", "firstOppositeAt", "nextSameColorStart", "trackingPriceExtremeAt", "trackingEndedAt", "disappearedAt"]) {
            if (s[k] !== null) {
                timeKey(s[k], period);
                assert(String(s[k]) <= through);
            }
        }
        const r = reference(s.originalReference, period, through);
        assert(r.endTime < String(s.originSegmentStart) && String(s.originSegmentStart) <= String(s.priceExtremeAt) && String(s.priceExtremeAt) <= String(s.formedAt) && finite(s.priceExtreme) && s.priceExtreme > 0);
        assert(Number.isInteger(s.nextSameColorCount) && Number(s.nextSameColorCount) >= 0 && ((s.nextSameColorStart === null) === (s.nextSameColorCount === 0)));
        if (s.firstOppositeAt === null) {
            assert(s.originWave === null && s.nextSameColorStart === null && s.trackingPriceExtreme === null && s.trackingPriceExtremeAt === null && s.formationRoute === "dif_turn" && s.status !== "FOLLOWING" && s.status !== "FINISHED");
        }
        else {
            const w = wave(s.originWave, period, through), sign = s.direction === "TOP" ? 1 : -1;
            assert(w.start === s.originSegmentStart && String(s.priceExtremeAt) <= w.end && w.end < String(s.firstOppositeAt) && String(s.formedAt) <= String(s.firstOppositeAt) && w.sign === sign && finite(s.trackingPriceExtreme) && s.trackingPriceExtreme > 0 && s.trackingPriceExtremeAt !== null && String(s.trackingPriceExtremeAt) >= String(s.firstOppositeAt));
            assert(sign * (Number(s.priceExtreme) - w.price) <= 0);
            assert((s.formationRoute === "color_flip") === (s.firstOppositeAt === s.formedAt));
            if (s.formationRoute === "dif_turn")
                assert(String(s.formedAt) <= w.end);
            if (s.nextSameColorStart !== null)
                assert(String(s.nextSameColorStart) > String(s.firstOppositeAt));
            assert((sign * (Number(s.trackingPriceExtreme) - w.price) > 0) === (s.status === "DISAPPEARED"));
        }
        if (s.status === "ASSESSING")
            assert(s.firstOppositeAt === null && s.trackingEndedAt === null && s.disappearedAt === null && s.disappearanceReason === null);
        if (s.status === "FOLLOWING")
            assert(s.firstOppositeAt !== null && s.trackingEndedAt === null && s.disappearedAt === null && s.disappearanceReason === null);
        if (s.status === "FINISHED")
            assert(s.firstOppositeAt !== null && s.nextSameColorStart !== null && Number(s.nextSameColorCount) >= 2 && s.trackingEndedAt !== null && String(s.trackingEndedAt) > String(s.nextSameColorStart) && s.trackingPriceExtremeAt !== null && String(s.trackingPriceExtremeAt) < String(s.trackingEndedAt) && s.disappearedAt === null && s.disappearanceReason === null);
        if (s.status === "DISAPPEARED") {
            assert(s.disappearedAt !== null && s.disappearedAt === s.trackingEndedAt && String(s.disappearedAt) >= String(s.formedAt) && ["dif_return", "reference_dif_break", "structure_price_break"].includes(String(s.disappearanceReason)));
            if (s.disappearedAt === s.formedAt)
                assert(s.formationRoute === "color_flip" && s.firstOppositeAt === s.disappearedAt);
            if (s.disappearanceReason === "structure_price_break")
                assert(s.firstOppositeAt !== null && String(s.disappearedAt) >= String(s.firstOppositeAt) && s.trackingPriceExtremeAt === s.disappearedAt && (s.nextSameColorStart === null || String(s.disappearedAt) >= String(s.nextSameColorStart)));
            else
                assert(s.firstOppositeAt === null);
        }
        if (s.formationRoute === "color_flip")
            assert(String(s.priceExtremeAt) < String(s.formedAt));
    }
    const structures = new Map(raw.structures.map(s => [s.id, s]));
    for (const [i, p] of raw.points.entries()) {
        check();
        keys(p, "time activeReference activeStructureId");
        assert(p.time === response.points[i]!.time);
        const ordinary = response.points[i]!;
        if (p.activeReference !== null) {
            assert(through);
            reference(p.activeReference, period, through);
            assert(String((p.activeReference as XxmReference).endTime) < ordinary.time);
        }
        assert((ordinary.ordinaryState === "NONE") === (p.activeReference === null));
        assert((ordinary.ordinaryState === "STRUCTURE") === (p.activeStructureId !== null));
        if (p.activeStructureId !== null) {
            const s = structures.get(p.activeStructureId);
            assert(s && s.direction === ordinary.ordinaryDirection && same(s.originalReference, p.activeReference) && String(s.formedAt) <= ordinary.time && (s.firstOppositeAt === null || ordinary.time < String(s.firstOppositeAt)) && (s.disappearedAt === null || ordinary.time < String(s.disappearedAt)));
        }
    }
    const ordinaryByTime = new Map<string, number[]>();
    const ranks = new Map<string, number>();
    for (const [i, e] of raw.events.entries()) {
        check();
        keys(e, "id route fromState eventReference relatedStructureId");
        const { time } = response.events[i]!;
        const priceBreak = e.route === "structure_price_break";
        const rank = priceBreak ? (structures.get(e.relatedStructureId)?.firstOppositeAt === time ? 2 : 0) : 1;
        assert(rank >= (ranks.get(time) ?? -1));
        ranks.set(time, rank);
        if (!priceBreak) {
            const indices = ordinaryByTime.get(time) ?? [];
            indices.push(i);
            ordinaryByTime.set(time, indices);
        }
    }
    const reactivationCancels = new Set<number>(), reactivations = new Set<number>();
    for (const indices of ordinaryByTime.values()) {
        if (indices.length === 1)
            continue;
        assert(indices.length === 2);
        const [cancelIndex, activationIndex] = indices as [number, number];
        const cancel = raw.events[cancelIndex], activation = raw.events[activationIndex];
        assert(cancel.route === "dif_break" && cancel.fromState === "STRUCTURE" && activation.route === "activation"
            && response.events[cancelIndex]!.direction === response.events[activationIndex]!.direction
            && record(activation.eventReference) && record(cancel.eventReference)
            && String(activation.eventReference.endTime) < String(cancel.eventReference.startTime));
        reactivationCancels.add(cancelIndex);
        reactivations.add(activationIndex);
    }
    const activation = new Set<string>();
    for (const [i, e] of raw.events.entries()) {
        check();
        const normal = response.events[i]!;
        assert(e.id === normal.id && through);
        reference(e.eventReference, period, through);
        assert((e.eventReference as XxmReference).endTime < normal.time);
        const allowed = { DULL: ["activation", "dif_return"], STRUCTURE: ["dif_turn", "color_flip"], CANCEL: ["dif_break", "dif_break_on_flip", "structure_price_break"] };
        assert(allowed[normal.type].includes(String(e.route)) && ["NONE", "DULL", "STRUCTURE"].includes(String(e.fromState)));
        if (normal.type === "CANCEL")
            assert(e.fromState === "DULL" || e.fromState === "STRUCTURE");
        else
            assert(e.fromState === (e.route === "activation" ? "NONE" : normal.type === "STRUCTURE" ? "DULL" : "STRUCTURE"));
        assert((normal.type === "STRUCTURE" || e.fromState === "STRUCTURE") === (e.relatedStructureId !== null));
        const related = e.relatedStructureId === null ? null : structures.get(e.relatedStructureId);
        assert(e.relatedStructureId === null || related && related.direction === normal.direction && same(related.originalReference, e.eventReference));
        if (e.route === "activation") {
            assert(e.fromState === "NONE" && e.relatedStructureId === null);
            activation.add(normal.time + normal.direction);
        }
        if (normal.type === "STRUCTURE") {
            const s = structures.get(e.relatedStructureId);
            assert(s && s.structureEventId === normal.id && s.formedAt === normal.time && s.direction === normal.direction && s.formationRoute === e.route && same(s.originalReference, e.eventReference) && e.fromState === "DULL");
        }
        if (e.route === "structure_price_break") {
            const s = structures.get(e.relatedStructureId);
            assert(s && s.status === "DISAPPEARED" && s.disappearedAt === normal.time && s.disappearanceReason === "structure_price_break" && s.direction === normal.direction && same(s.originalReference, e.eventReference) && e.fromState === "STRUCTURE");
        }
        if (related && normal.type !== "STRUCTURE")
            assert(related.status === "DISAPPEARED" && related.disappearedAt === normal.time && related.disappearanceReason === (e.route === "dif_return" ? "dif_return" : e.route === "structure_price_break" ? "structure_price_break" : "reference_dif_break"));
        const pointIndex = response.points.findIndex(p => p.time === normal.time), point = response.points[pointIndex]!, detail = raw.points[pointIndex]!;
        if (["activation", "dif_return", "dif_turn"].includes(String(e.route))) {
            assert(point.ordinaryState === (e.route === "dif_turn" ? "STRUCTURE" : "DULL") && point.ordinaryDirection === normal.direction && same(detail.activeReference, e.eventReference));
            if (e.route === "dif_turn")
                assert(detail.activeStructureId === e.relatedStructureId);
        }
        else if (e.route !== "structure_price_break" && !reactivationCancels.has(i))
            assert(point.ordinaryState === "NONE");
        if (e.route !== "structure_price_break" && pointIndex && !reactivations.has(i)) {
            assert(e.fromState === response.points[pointIndex - 1]!.ordinaryState);
            if (reactivationCancels.has(i)) {
                const prior = raw.points[pointIndex - 1]!;
                assert(same(prior.activeReference, e.eventReference) && prior.activeStructureId === e.relatedStructureId);
            }
        }
    }
    for (const [i, e] of raw.events.entries()) {
        const n = response.events[i]!;
        const hiddenPriceBreak = n.type === "CANCEL" && e.route === "structure_price_break"
            && activation.has(n.time + n.direction);
        assert(n.displayOnChart === !(hiddenPriceBreak || reactivationCancels.has(i)));
    }
    for (const s of raw.structures) {
        if (response.points.some(p => p.time === s.formedAt))
            assert(response.events.some(e => e.id === s.structureEventId && e.type === "STRUCTURE"));
        if (response.points.some(p => p.time === s.disappearedAt))
            assert(raw.events.filter((e, i) => e.relatedStructureId === s.id && response.events[i]!.time === s.disappearedAt && response.events[i]!.type !== "STRUCTURE").length === 1);
    }
    assert(raw.structures.filter(s => s.status === "ASSESSING").length <= 1);
    if (response.points.at(-1)?.time === through) {
        const last = raw.points.at(-1)!;
        const assessing = raw.structures.filter(s => s.status === "ASSESSING");
        assert(assessing.length === (last.activeStructureId === null ? 0 : 1) && (last.activeStructureId === null || assessing[0]!.id === last.activeStructureId));
    }
    for (const direction of ["TOP", "BOTTOM"])
        assert(raw.structures.filter(s => s.status === "FOLLOWING" && s.direction === direction).length <= 1);
    check();
    return raw as unknown as XxmDebugData;
};
