จากโค้ดปัจจุบัน Flow หลักมีดังนี้

  ## 1. Application Startup

  flowchart TD
      A[Start Uvicorn] --> B[app.main:create_app]
      B --> C[Setup Logging / Logfire]
      C --> D[Register Middleware]
      D --> E[Register Exception Handlers]
      E --> F[Include API Router /api/v1]
      F --> G[Startup Lifespan]
      G --> H[Connect Redis]
      G --> I[Create ARQ Worker Pool]
      G --> J[Ready to receive requests]
      J --> K[Shutdown]
      K --> L[Close ARQ]
      K --> M[Close Redis]
      K --> N[Close Database]

  จุดเริ่มต้นอยู่ที่ main.py (backend/app/main.py)

  ทรัพยากรที่ถูกเตรียมตอนเริ่มระบบ:

  - PostgreSQL ผ่าน SQLAlchemy AsyncSession
  - Redis
  - ARQ สำหรับ background jobs
  - Logfire observability
  - FastAPI middleware เช่น CORS, Session, Request ID

  ———

  ## 2. HTTP Request Flow ทั่วไป

  flowchart LR
      A[Client / Frontend] --> B[FastAPI Middleware]
      B --> C[API Router /api/v1]
      C --> D[Route Handler]
      D --> E[Dependency Injection]
      E --> F[Authentication / Authorization]
      F --> G[Service]
      G --> H[Repository]
      H --> I[(PostgreSQL)]
      I --> H
      H --> G
      G --> D
      D --> J[JSON Response]

  โครงสร้าง Layer:

  Route
    ↓
  Dependency
    ↓
  Service
    ↓
  Repository
    ↓
  Database Model
    ↓
  PostgreSQL

  ตัวอย่างเช่น GET /api/v1/auth/me

  Request
    ↓
  auth.py:get_current_user_info
    ↓
  deps.py:get_current_user
    ↓
  verify JWT token
    ↓
  UserService.get_by_id()
    ↓
  user_repository.get_by_id()
    ↓
  PostgreSQL
    ↓
  User object
    ↓
  UserRead response

  Repository ใช้ flush() และ transaction จะถูก commit() ที่ get_db_session() หลัง route ทำงานสำเร็จ หากเกิด exception จะ
  rollback() อัตโนมัติ

  ดูได้จาก:

  - api/deps.py (backend/app/api/deps.py)
  - db/session.py (backend/app/db/session.py)
  - api/routes/v1/init.py (backend/app/api/routes/v1/__init__.py)

  ———

  ## 3. Login Flow

  sequenceDiagram
      participant F as Frontend
      participant A as Auth Route
      participant S as UserService
      participant R as UserRepository
      participant DB as PostgreSQL

      F->>A: POST /api/v1/auth/login
      A->>S: authenticate(email, password)
      S->>R: get_by_email(email)
      R->>DB: SELECT user
      DB-->>R: User
      R-->>S: User
      S->>S: verify_password()
      S-->>A: Authenticated User
      A->>A: create_access_token()
      A->>A: create_refresh_token()
      A-->>F: access_token + refresh_token

  JWT มี 2 ประเภท:

  - access token ใช้เรียก API และ WebSocket
  - refresh token ใช้ขอ access token ใหม่

  การตรวจสอบผู้ใช้ทั่วไป:

  JWT
    ↓
  verify_token()
    ↓
  ตรวจ type == "access"
    ↓
  ดึง user_id จาก sub
    ↓
  ค้นหา User จาก Database
    ↓
  ตรวจ is_active
    ↓
  อนุญาตให้เข้า Endpoint

  ———

  ## 4. File Upload Flow

  flowchart TD
      A[User เลือกไฟล์] --> B[POST /api/v1/files/upload]
      B --> C[อ่านไฟล์เป็น bytes]
      C --> D[Validate MIME type และขนาด]
      D --> E[Classify file type]
      E --> F{ประเภทไฟล์}
      F -->|PDF / DOCX / Text| G[Parse text content]
      F -->|Image| H[ไม่ parse เก็บ binary]
      G --> I[บันทึกลง File Storage]
      H --> I
      I --> J[สร้าง ChatFile record]
      J --> K[(PostgreSQL)]
      J --> L[ส่ง file_id กลับ Frontend]

  ประเภทไฟล์ที่รองรับโดยทั่วไป:

  image → ส่งเข้า AI เป็น BinaryContent
  pdf/docx/txt/md → แยกข้อความแล้วแนบเข้า prompt

  โค้ดหลักอยู่ที่:

  - files.py (backend/app/api/routes/v1/files.py)
  - file_upload.py (backend/app/services/file_upload.py)
  - file_storage.py (backend/app/services/file_storage.py)

  ———

  ## 5. Chat / AI Agent Flow ที่ทำงานจริงในปัจจุบัน

  Frontend เปิด WebSocket ไปที่:

  /api/v1/ws/agent

  sequenceDiagram
      participant F as Frontend
      participant WS as WebSocket Route
      participant AG as AssistantAgent
      participant AI as Google Gemini
      participant FS as File Storage / DB

      F->>WS: Connect /ws/agent
      F->>WS: {message, file_ids, model, temperature}
      WS-->>F: model_request_start

      alt มีไฟล์แนบ
          WS->>FS: Load attached files
          FS-->>WS: Image binary / parsed text
          WS->>WS: Build multimodal input
      end

      WS->>AG: get_agent(...)
      AG->>AG: Build GoogleModel
      AG->>AG: Build message history
      AG->>AI: agent.run(prompt, history, deps)
      AI-->>AG: Generated response
      AG-->>WS: output

      WS-->>F: text_delta
      WS-->>F: final_result
      WS-->>F: complete

  ลำดับ Event ที่ Frontend รองรับ:

  model_request_start
    ↓
  text_delta
    ↓
  final_result
    ↓
  complete

  โค้ดหลัก:

  - Backend: agent.py (backend/app/api/routes/v1/agent.py)
  - AI Agent: assistant.py (backend/app/agents/assistant.py)
  - Frontend Chat Hook: use-chat.ts (frontend/src/hooks/use-chat.ts)

  ———

  ## 6. AI Agent ภายใน

  flowchart TD
      A[User Message] --> B[AssistantAgent.run]
      B --> C[สร้าง GoogleModel]
      C --> D[สร้าง System Prompt]
      D --> E[แปลง History เป็น Model Messages]
      E --> F[Register Tools]
      F --> G[เรียก PydanticAI]
      G --> H[Google Gemini]
      H --> I{ต้องใช้ Tool หรือไม่}
      I -->|ไม่ใช้| J[ส่งข้อความตอบกลับ]
      I -->|ใช้| K[เรียก Tool]
      K --> L[ส่งผล Tool กลับให้ Model]
      L --> J

  Tool ที่มีอยู่ใน Agent ตอนนี้คือ:

  current_datetime()

  Agent ใช้ข้อมูลจาก:

  - DEFAULT_SYSTEM_PROMPT
  - history
  - Deps
  - model ที่กำหนดใน settings.AI_MODEL
  - GOOGLE_API_KEY

  ———

  ## 7. Error Flow

  flowchart TD
      A[เกิด Exception] --> B{เป็น AppException หรือไม่}
      B -->|ใช่| C[app_exception_handler]
      B -->|ไม่ใช่| D[Unhandled Exception]
      C --> E[แปลงเป็น JSON error]
      D --> F[Log exception]
      F --> G[ตอบ INTERNAL_ERROR]
      E --> H[Client]
      G --> H

  รูปแบบ Error จาก Backend:

  {
    "error": {
      "code": "ERROR_CODE",
      "message": "Readable error message",
      "details": null
    }
  }

  ดูได้จาก exception_handlers.py (backend/app/api/exception_handlers.py)

  ———

  ## ข้อสังเกตสำคัญจากโค้ดปัจจุบัน

  มีโค้ดสองแนวทางสำหรับ Agent Session:

  1. Route ปัจจุบันใน api/routes/v1/agent.py (backend/app/api/routes/v1/agent.py)
  2. AgentSession ใน services/agent_session.py (backend/app/services/agent_session.py)

  แต่ Route ปัจจุบันเรียก AssistantAgent.run() โดยตรง ดังนั้นใน flow ที่ทำงานจริงตอนนี้:

  - ยังไม่มีการบันทึก conversation/message จาก WebSocket route
  - ยังไม่ได้ใช้ AgentSession.process_message()
  - Event เช่น conversation_created และ message_saved อาจไม่ถูกส่งจาก route นี้
  - Frontend มี logic รองรับ event เหล่านี้อยู่แล้ว แต่ Backend route ปัจจุบันไม่ได้ emit
  - get_current_user_ws() มีอยู่ใน deps.py แต่ไม่ได้ถูกผูกเข้ากับ @router.websocket("/ws/agent") ใน route ปัจจุบัน

  ดังนั้นภาพรวมที่ถูกต้องที่สุดของ implementation ตอนนี้คือ:

  Frontend
    ↓
  WebSocket /api/v1/ws/agent
    ↓
  รับ message
    ↓
  โหลดไฟล์แนบ
    ↓
  สร้าง AssistantAgent
    ↓
  เรียก Google Gemini ผ่าน PydanticAI
    ↓
  ส่ง output กลับ Frontend
    ↓
  จบ turn

  ส่วน flow ที่มีการ persist conversation จะอยู่ใน AgentSession แต่ยังไม่ได้ถูกใช้โดย WebSocket route ปัจจุบันครับ