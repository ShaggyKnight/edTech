"""Carrito del cliente online.

Reusa `pos.cart.Cart` pero con una session_key y un canal propios para no
colisionar con un cajero que también use POS en la misma sesión del
navegador.
"""

from pos.cart import Cart as _BaseCart

SESSION_KEY = 'ecommerce_cart'
CANAL = 'online'


class Cart(_BaseCart):
    def __init__(self, session):
        super().__init__(session, session_key=SESSION_KEY)

    def lineas(self, canal: str = CANAL):
        return super().lineas(canal=canal)

    def totales(self, canal: str = CANAL):
        return super().totales(canal=canal)
