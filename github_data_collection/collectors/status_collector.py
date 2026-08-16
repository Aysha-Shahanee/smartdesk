def extract_status(project_data):


    owner_data = project_data.get("user") or project_data.get("organization") or {}
    items = owner_data.get("projectV2", {}).get("items", {}).get("nodes", [])


    statuses=[]


    for item in items:


        statuses.append({

            "item_id":
            item.get("id"),


            "type":
            item.get("type")


        })


    return statuses
