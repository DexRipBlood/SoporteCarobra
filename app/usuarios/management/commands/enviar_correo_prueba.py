from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.template.loader import render_to_string


class Command(BaseCommand):
    help = "Envía un correo corporativo de prueba sin crear una cuenta."

    def add_arguments(self, parser):
        parser.add_argument("destinatario", help="Dirección que recibirá la prueba")
        parser.add_argument(
            "--url",
            dest="access_url",
            default=settings.PUBLIC_BASE_URL,
            help="URL que abrirá el botón del correo",
        )

    def handle(self, *args, **options):
        destinatario = options["destinatario"].strip().lower()
        access_url = options["access_url"].strip().rstrip("/")

        try:
            validate_email(destinatario)
        except ValidationError as error:
            raise CommandError("La dirección de correo no es válida.") from error

        if not settings.EMAIL_CONFIGURED:
            raise CommandError("La configuración SMTP no está completa.")

        context = {
            "destinatario": destinatario,
            "access_url": access_url,
        }
        text_body = render_to_string(
            "usuarios/emails/prueba.txt",
            context,
        )
        html_body = render_to_string(
            "usuarios/emails/prueba.html",
            context,
        )
        message = EmailMultiAlternatives(
            subject="Prueba de correo · CAROBRA Operations Center",
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destinatario],
        )
        message.attach_alternative(html_body, "text/html")

        try:
            sent = message.send(fail_silently=False)
        except Exception as error:
            raise CommandError(f"No se pudo enviar el correo: {error}") from error

        if sent != 1:
            raise CommandError("El servidor SMTP no confirmó el envío.")

        self.stdout.write(
            self.style.SUCCESS(f"Correo de prueba enviado a {destinatario}.")
        )
