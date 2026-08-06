class CorsMiddleware:
    """
    Middleware personalizado para gestionar las cabeceras de Cross-Origin Resource Sharing (CORS)
    asegurando la comunicación segura entre el frontend en Vanilla JS y la API REST de Django.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Si la petición es de tipo preflight (OPTIONS), respondemos inmediatamente con los permisos
        if request.method == "OPTIONS":
            response = self.get_response(request) if hasattr(self, 'get_response') else type('obj', (object,), {'status_code': 200})()
            response.status_code = 200
        else:
            response = self.get_response(request)

        # Configuración de políticas de acceso industrial para la plataforma MES
        response["Access-Control-Allow-Origin"] = "*"  # En producción se restringirá al dominio autorizado del frontend
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Accept, Content-Type, Authorization, X-Requested-With, X-CSRFToken"
        response["Access-Control-Allow-Credentials"] = "true"
        
        return response
