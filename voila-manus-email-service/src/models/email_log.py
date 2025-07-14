from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False)
    customer_name = db.Column(db.String(255), nullable=False)
    property_title = db.Column(db.String(500), nullable=False)
    email_subject = db.Column(db.String(500), nullable=False)
    email_content = db.Column(db.Text, nullable=False)
    email_type = db.Column(db.String(50), nullable=False, default='order_confirmation')
    status = db.Column(db.String(50), nullable=False, default='pending')
    resend_message_id = db.Column(db.String(100), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'customer_email': self.customer_email,
            'customer_name': self.customer_name,
            'property_title': self.property_title,
            'email_subject': self.email_subject,
            'email_content': self.email_content,
            'email_type': self.email_type,
            'status': self.status,
            'resend_message_id': self.resend_message_id,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

