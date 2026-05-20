# Betting Monolithic Service

This is the monolithic version of the betting application, converted from microservices architecture. It includes all the authentication functionality that was previously in the `betting_auth_service`.

## 🚀 Quick Start

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Setup**
   ```bash
   cp .env.example .env
   # Edit .env file with your configuration values
   ```

3. **Run the Application**
   ```bash
   python run.py
   ```

4. **Access the API**
   - API Documentation: http://localhost:8000/docs
   - ReDoc Documentation: http://localhost:8000/redoc
   - Health Check: http://localhost:8000/health

## 📡 API Endpoints

### Authentication Endpoints (Preserved from microservice)

All authentication endpoints maintain the **exact same** API structure as the original microservice:

#### Registration
- `POST /auth/register` - User registration
- `POST /auth/complete-profile` - Complete profile after subscription

#### Login
- `POST /auth/send-otp` - Send OTP for phone login
- `POST /auth/verify-otp` - Verify OTP and login
- `POST /auth/resend-otp` - Resend OTP
- `POST /auth/login` - Email/password login
- `POST /auth/refresh-token` - Refresh access token
- `POST /auth/logout` - Logout user
- `GET /auth/sessions` - Get active sessions

#### Password Management
- `POST /auth/forgot-password` - Request password reset
- `POST /auth/reset-password` - Reset password with token

#### Social Login
- `POST /social/login` - Social media login (Google, Apple, Facebook)

#### Trial Membership
- `POST /trial/start` - Start trial membership
- `GET /trial/status/{user_id}` - Get trial status
- `POST /trial/refund` - Request trial refund
- `GET /trial/offer` - Get trial offer details
- `GET /trial/captain-offer` - Get captain trial offer

#### Club Membership
- `GET /membership/details/{club_id}` - Get club membership details
- `GET /membership/active/{user_id}` - Get active memberships
- `GET /membership/past/{user_id}` - Get past memberships
- `POST /membership/join` - Join club membership
- `GET /membership/status` - Check membership status

## 🔧 Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

- **Database**: MongoDB connection string
- **JWT**: Secret key and token expiration settings
- **Twilio**: SMS service for OTP
- **Email**: SMTP settings for email notifications
- **Stripe**: Payment processing
- **OAuth**: Google, Apple, Facebook social login
- **Frontend**: URLs for redirects

### Database

The application uses MongoDB. Ensure your MongoDB instance is running and accessible via the `MONGODB_URL` in your `.env` file.

## 🛠️ Development

### Running in Development Mode
```bash
python run.py
```

### Running with Custom Port
```bash
PORT=8080 python run.py
```

### API Testing
Use the built-in Swagger UI at `/docs` or any API client like Postman to test the endpoints.

## 📦 Project Structure

```
.
├── main.py                 # Main FastAPI application
├── run.py                  # Application startup script
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── auth/                  # Authentication module
│   ├── models.py          # Pydantic models
│   ├── utils.py           # Utility functions
│   ├── db.py              # Database connection
│   └── routes/            # API route handlers
│       ├── registration.py
│       ├── login.py
│       ├── email_login.py
│       ├── password_reset.py
│       ├── social_login.py
│       └── trial_membership.py
└── static/                # Static files (HTML templates)
    ├── payment_success.html
    └── payment_cancel.html
```

## 🔄 Migration from Microservices

This monolithic service maintains **100% API compatibility** with the original microservices:

- ✅ All endpoint URLs remain the same
- ✅ All request/response formats are preserved
- ✅ All headers and authentication remain unchanged
- ✅ Frontend integration works without any changes

### Original Microservice Endpoints Preserved

- All `/auth/*` endpoints work exactly the same
- All `/social/*` endpoints work exactly the same  
- All `/trial/*` endpoints work exactly the same
- All `/membership/*` endpoints work exactly the same

## 🚀 Deployment

### Using Python directly
```bash
python run.py
```

### Using Uvicorn directly
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Using Docker (if needed)
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "run.py"]
```

## 🔍 Health Monitoring

- Health Check: `GET /health`
- Service Status: `GET /`

Both endpoints return service status and confirm all modules are running correctly.

---

**Note**: This monolithic service is a direct conversion from the original microservices architecture. No functionality has been changed - only the deployment model has been unified. 