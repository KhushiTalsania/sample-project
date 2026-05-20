"""
Centralized Response Utilities

This module provides standardized response formatting across all services.
"""

from fastapi.responses import JSONResponse
from typing import Any, Optional, Dict
from datetime import datetime

def create_response(
    status_code: int,
    status: str,
    message: str,
    data: Optional[Any] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Create standardized API response.
    
    Args:
        status_code: HTTP status code
        status: Status string (success/error/warning)
        message: Response message
        data: Response data (optional)
        error: Error code (optional)
        metadata: Additional metadata (optional)
        
    Returns:
        JSONResponse with standardized format
    """
    response_body = {
        "status": status,
        "message": message,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    if data is not None:
        response_body["data"] = data
    
    if error is not None:
        response_body["error"] = error
    
    if metadata is not None:
        response_body["metadata"] = metadata
    
    return JSONResponse(
        status_code=status_code,
        content=response_body
    )

def create_success_response(
    message: str,
    data: Optional[Any] = None,
    status_code: int = 200,
    metadata: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Create success response.
    
    Args:
        message: Success message
        data: Response data (optional)
        status_code: HTTP status code (default 200)
        metadata: Additional metadata (optional)
        
    Returns:
        JSONResponse with success format
    """
    return create_response(
        status_code=status_code,
        status="success",
        message=message,
        data=data,
        metadata=metadata
    )

def create_error_response(
    message: str,
    error: Optional[str] = None,
    status_code: int = 400,
    data: Optional[Any] = None
) -> JSONResponse:
    """
    Create error response.
    
    Args:
        message: Error message
        error: Error code (optional)
        status_code: HTTP status code (default 400)
        data: Additional error data (optional)
        
    Returns:
        JSONResponse with error format
    """
    return create_response(
        status_code=status_code,
        status="error",
        message=message,
        error=error,
        data=data
    )

def create_validation_error_response(
    field: str,
    message: str,
    status_code: int = 422
) -> JSONResponse:
    """
    Create validation error response.
    
    Args:
        field: Field that failed validation
        message: Validation error message
        status_code: HTTP status code (default 422)
        
    Returns:
        JSONResponse with validation error format
    """
    return create_response(
        status_code=status_code,
        status="error",
        message=message,
        error="validation_failed",
        data={"field": field}
    )

def create_pagination_response(
    items: list,
    total: int,
    page: int,
    page_size: int,
    message: str = "Data retrieved successfully"
) -> JSONResponse:
    """
    Create paginated response.
    
    Args:
        items: List of items for current page
        total: Total number of items
        page: Current page number
        page_size: Items per page
        message: Response message
        
    Returns:
        JSONResponse with pagination metadata
    """
    total_pages = (total + page_size - 1) // page_size
    
    metadata = {
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
    }
    
    return create_success_response(
        message=message,
        data=items,
        metadata=metadata
    ) 