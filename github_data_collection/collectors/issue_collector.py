def extract_issue_metadata(project_data):


    tasks = []


    owner_data = project_data.get("user") or project_data.get("organization") or {}
    items = owner_data.get("projectV2", {}).get("items", {}).get("nodes", [])


    for item in items:


        content = item.get(
            "content"
        )


        if not content:
            continue



        task = {


            "id":
            content.get("id"),


            "title":
            content.get("title"),


            "description":
            content.get("body"),


            "state":
            content.get("state"),


            "created_at":
            content.get("createdAt"),


            "updated_at":
            content.get("updatedAt"),



            "labels":

            [
                label["name"]

                for label in

                content
                .get("labels", {})
                .get("nodes", [])

            ],



            "assignees":

            [
                user["login"]

                for user in

                content
                .get("assignees", {})
                .get("nodes", [])

            ]

        }


        tasks.append(task)



    return tasks
