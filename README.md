# E-Prestasi

E-Prestasi is a Django-based student achievement management system built for SMKN 11 Bandung. The platform helps students document their achievements, allows school staff to verify them, and showcases public student portfolios with a searchable and structured workflow.

The application is designed around the needs of a school environment, covering student records, achievement verification, class management, academic years, graduation tracking, and public portfolio access.

## Features

- Student account management and profile completion
- Admin and super-admin dashboards
- Kesiswaan verification workflow for submitted achievements
- Achievement upload with supporting documents and certificates
- Category, year, and level-based achievement records
- Searchable public student portfolio pages
- QR code and public profile access
- Excel import for bulk student data management
- Class and academic-year administration
- Graduation and alumni tracking
- Notification and activity logging
- Cloudinary storage for uploaded media and documents

## Tech Stack

- Python
- Django 6
- PostgreSQL
- Cloudinary
- WhiteNoise
- qrcode
- openpyxl
- Django template system and custom CSS styling

## Project Structure

```text
D:/djanggo/
├── config/                 # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── eprestasi/              # Main application code
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   ├── templates/
│   ├── static/
│   └── management/
├── static/                 # Global static assets
├── templates/              # Shared templates
├── .env                    # Local environment variables
├── manage.py
├── requirements.txt
├── vercel.json
├── README.md
└── .gitignore
```

## Main Roles

The application is structured around these user roles:

- `super_admin`
- `admin`
- `kesiswaan`
- `siswa`

## Prerequisites

Before running the project, make sure you have:

- Python 3.10 or newer
- PostgreSQL database
- Cloudinary account and URL
- A virtual environment tool such as `venv`

## Setup Instructions

1. Clone the project and open the repository directory.

2. Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure environment variables in a `.env` file. Example:

```env
SECRET_KEY=your-secret-key
DEBUG=True
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
```

5. Run database migrations:

```bash
python manage.py migrate
```

6. Create an admin account:

```bash
python manage.py createsuperuser
```

7. Start the development server:

```bash
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/
```

## Common Commands

```bash
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic
```

## Deployment Notes

This project includes a `vercel.json` configuration, so it can be adapted for Vercel deployment. For production deployment, set the required environment variables securely and ensure the correct host/domain is allowed in Django settings.

The app uses `whitenoise` for static file serving and Cloudinary for document/media storage.

## Notes

This project is intended for school administration and student achievement management, especially for internal use in a vocational high school context. The landing page and branding are aligned with the SMKN 11 Bandung identity shown in the app.
