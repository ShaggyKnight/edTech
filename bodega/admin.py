from django.contrib import admin

from .models import *



class ProductoInLine(admin.TabularInline):
	model = ProductoAtributo


class ProductAdmin(admin.ModelAdmin):
	inlines = [
		ProductoInLine,		
	]

admin.site.register(Producto, ProductAdmin)
admin.site.register(Bodega)
admin.site.register(Atributo)
admin.site.register(Familia)
admin.site.register(Material)
admin.site.register(Inventario)
admin.site.register(Inventariolinea)

