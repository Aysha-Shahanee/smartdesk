from ..github_client import execute_query
from ..config import (
    GITHUB_OWNER,
    PROJECT_NUMBER
)



def _build_query(owner_type: str) -> str:

    return f"""

    query(
      $owner:String!,
      $number:Int!,
      $cursor:String
    ){{

      {owner_type}(login:$owner){{

        projectV2(number:$number){{

          items(first:100, after:$cursor){{

            pageInfo{{ hasNextPage endCursor }}

            nodes{{

              id

              type


              content{{

                ... on Issue{{

                  id

                  title

                  body

                  state


                  createdAt

                  updatedAt


                  labels(first:10){{

                    nodes{{

                      name

                    }}

                  }}


                  assignees(first:5){{

                    nodes{{

                      login

                    }}

                  }}

                }}

              }}

            }}

          }}

        }}

      }}

    }}

    """



def _query_owner_types():
    return ["user", "organization"]



def get_project_items():

    variables = {
        "owner": GITHUB_OWNER,
        "number": PROJECT_NUMBER,
        "cursor": None,
    }

    for owner_type in _query_owner_types():
        try:
            project_data = execute_query(
                _build_query(owner_type),
                variables
            )
        except Exception as exc:
            error_text = str(exc)
            if (
                "Resource not accessible by personal access token" in error_text
                or "FORBIDDEN" in error_text
                or "Could not resolve to an Organization with the login" in error_text
                or "Could not resolve to a User with the login" in error_text
            ):
                continue
            raise

        owner_data = project_data.get(owner_type)
        if owner_data and owner_data.get("projectV2") is not None:
            owner_data = project_data[owner_type]
            project = owner_data["projectV2"]
            connection = project["items"]
            nodes = list(connection.get("nodes") or [])
            while (connection.get("pageInfo") or {}).get("hasNextPage"):
                variables["cursor"] = connection["pageInfo"]["endCursor"]
                next_data = execute_query(_build_query(owner_type), variables)
                connection = next_data[owner_type]["projectV2"]["items"]
                nodes.extend(connection.get("nodes") or [])
            project["items"]["nodes"] = nodes
            return project_data

    raise Exception(
        f"Project {PROJECT_NUMBER} not accessible for owner '{GITHUB_OWNER}'. "
        "Confirm the owner value is correct, the project number exists, and the PAT has project access."
    )
