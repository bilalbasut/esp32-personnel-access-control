from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Card
from .serializers import CardSerializer

class CardViewSet(viewsets.ModelViewSet):
    queryset = Card.objects.all()
    serializer_class = CardSerializer

    # Replaces a raw FBV like `def deactivate_card(request, pk):`
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        card = self.get_object()
        card.is_active = False
        card.save()
        return Response({'status': 'Card deactivated', 'uid': card.uid})

    # Replaces a raw FBV like `def process_rfid_scan(request):`
    @action(detail=True, methods=['post'])
    def scan(self, request, pk=None):
        card = self.get_object()
        if not card.is_active:
            return Response(
                {'error': 'Card is inactive'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        # Log the access attempt, validate zones, etc.
        return Response({'status': 'Access granted', 'employee': card.employee_name})