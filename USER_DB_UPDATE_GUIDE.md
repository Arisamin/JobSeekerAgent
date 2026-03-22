# UserDBUpdate Mode Usage Guide

## What is UserDBUpdate Mode?

UserDBUpdate is an interactive mode that allows you to manage job application statuses without running the autonomous agent. It provides a simple terminal UI to:
- View all jobs in the database
- Update job status
- Track application progress

## Status Types

- **Applied**: You submitted an application for this job
- **InProcess**: You are in the middle of a process with them
- **RejectedMe**: They have rejected you
- **RejectedByMe**: You have rejected the job
- **Accepted**: They have accepted you

## How to Run

```powershell
cd "c:\MyData\Git\AI Projects\Job Seeker Agent"
& ".venv/Scripts/python.exe" "agent_engine.py" --user-db-update
```

## Important Notes

1. **Exclusive Lock**: The database is locked while in UserDBUpdate mode. This prevents the autonomous agent from running concurrently.
2. **Lock Timeout**: If the lock acquisition times out (10 seconds), it means another instance is running. Stop the other agent first.
3. **Timestamps**: Each job update automatically records the `last_updated` timestamp.
4. **No Browser**: This mode does not launch a browser; it only manages the database.

## Example Session

```
============================================================
   JOB STATUS UPDATE MODE
============================================================

📋 Found 5 job(s) in database:

  [1] → Senior Software Engineer (Python & Networking) @ Axonius [Applied]
  [2] → Senior Backend Engineer @ Lemonade [Applied]
  [3] ✓ Embedded Software Engineer, AWS Annapurna Labs @ Amazon Web Services (AWS) [Accepted]
  [4] → Software Engineer, Backend @ Semperis [Applied]
  [5] → Senior C# Developer @ Yael Korentec Technologies [Applied]

  [0] Done / Exit

Select job number to update (0 to exit): 2

------------------------------------------------------------
Job: Senior Backend Engineer
Company: Lemonade
URL: https://www.linkedin.com/jobs/view/...
Current Status: Applied
Created: 2026-03-22T16:01:42.xxx
Last Updated: 2026-03-22T16:01:42.xxx
------------------------------------------------------------

Select new status:

  [1] Applied  
  [2] InProcess  
  [3] RejectedMe  
  [4] RejectedByMe  
  [5] Accepted 

Enter new status number: 2

✅ Status updated to: InProcess

(Form resets and you can select another job)
```

## Workflow

1. Run the agent in normal mode to extract jobs: `python agent_engine.py --headless`
2. Once you have jobs in the database, run UserDBUpdate to track progress: `python agent_engine.py --user-db-update`
3. Select jobs and update their status as your application process progresses
4. Press "0" or "Done" to exit and release the database lock
