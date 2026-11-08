"""Decide which recognition events appear on the chart."""


def event_display_flags(events):
    activations = {(event["time"], event["direction"]): event for event in events
                   if event["type"] == "DULL" and event["route"] == "activation"}
    flags = {}
    for event in events:
        activation = activations.get((event["time"], event["direction"]))
        hide = event["type"] == "CANCEL" and activation is not None and (
            event["route"] == "structure_price_break"
            or (event["route"] == "dif_break" and event["fromState"] == "STRUCTURE"
                and event["relatedStructureId"] is not None and activation["fromState"] == "NONE"
                and activation["relatedStructureId"] is None
                and event["eventReference"] != activation["eventReference"])
        )
        flags[event["id"]] = not hide
    return flags
