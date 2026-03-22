```mermaid
%%{init: {
    "theme": "base",
    "flowchart": {
        "useMaxWidth": false,
        "htmlLabels": true,
        "nodeSpacing": 10,
        "rankSpacing": 40,
        "diagramPadding": 20
    },
    "themeVariables": {
        "fontSize": "10px"
    }
}}%%
graph TD
    start([Start UserDBUpdate Mode])
    step_1_0[1.0 Acquire database lock]
    step_1_0_1{1.0.1 Lock acquired?}
    step_1_1[1.1 Failed - another agent running]
    
    step_2_0[2.0 Load all jobs from database]
    step_2_0_1{2.0.1 Jobs found?}
    step_2_1[2.1 Display no jobs message]
    
    step_3_0[3.0 Display job list with current status]
    step_3_1[3.1 Prompt user to select job by number]
    step_3_1_1{3.1.1 User input valid?}
    step_3_2[3.2 Invalid input - show error]
    
    step_3_1_2{3.1.2 User selects Done?}
    
    step_4_0[4.0 Display selected job details]
    step_4_1[4.1 Show current status and URL]
    
    step_5_0[5.0 Display status options dropdown]
    step_5_1[5.1 Prompt user to select new status]
    step_5_1_1{5.1.1 User input valid?}
    step_5_2[5.2 Invalid status selection]
    
    step_6_0[6.0 Update database with new status]
    step_6_1[6.1 Update last_updated timestamp]
    step_6_2[6.2 Log status change]
    step_6_3[6.3 Display success message]
    
    step_7_0[7.0 Reset form to initial state]
    step_7_1[7.1 Return to job list]
    
    step_8_0[8.0 Release database lock]
    step_8_1[8.1 Close database connection]
    end([End])

    start --> step_1_0
    step_1_0 --> step_1_0_1
    step_1_0_1 -- "No" --> step_1_1
    step_1_1 --> end
    step_1_0_1 -- "Yes" --> step_2_0
    
    step_2_0 --> step_2_0_1
    step_2_0_1 -- "No" --> step_2_1
    step_2_1 --> step_8_0
    step_2_0_1 -- "Yes" --> step_3_0
    
    step_3_0 --> step_3_1
    step_3_1 --> step_3_1_1
    step_3_1_1 -- "No" --> step_3_2
    step_3_2 --> step_3_1
    step_3_1_1 -- "Yes" --> step_3_1_2
    step_3_1_2 -- "Yes (Done)" --> step_8_0
    step_3_1_2 -- "No" --> step_4_0
    
    step_4_0 --> step_4_1
    step_4_1 --> step_5_0
    step_5_0 --> step_5_1
    step_5_1 --> step_5_1_1
    step_5_1_1 -- "No" --> step_5_2
    step_5_2 --> step_5_1
    step_5_1_1 -- "Yes" --> step_6_0
    
    step_6_0 --> step_6_1
    step_6_1 --> step_6_2
    step_6_2 --> step_6_3
    step_6_3 --> step_7_0
    step_7_0 --> step_7_1
    step_7_1 --> step_3_0
    
    step_8_0 --> step_8_1
    step_8_1 --> end

    classDef x0Step fill:#FFE000,stroke:#B58900,stroke-width:2px,color:#111111;
    classDef waitStep fill:#FFA500,stroke:#B58900,stroke-width:2px,color:#111111;
    classDef normalStep fill:#ECECFF,stroke:#9370DB,stroke-width:1px,color:#333333;

    class step_1_0,step_2_0,step_3_0,step_4_0,step_5_0,step_6_0,step_7_0,step_8_0 x0Step;
    class step_1_0_1,step_2_0_1,step_3_1_1,step_3_1_2,step_5_1_1 normalStep;
    class step_1_1,step_2_1,step_3_2,step_5_2,step_3_1,step_3_2,step_4_1,step_5_1,step_6_1,step_6_2,step_6_3,step_7_1,step_8_1 normalStep;
```
