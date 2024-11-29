import os
import time
import signal
from datetime import datetime, timedelta
import binance
from binance.client import Client
from getpass import getpass

# Variables globales para las estadísticas de la sesión
operaciones_realizadas = []
saldo_inicial = 0.0
saldo_actual = 0.0
api_key_global = None
api_secret_global = None

# Función para validar la API y la clave secreta
def validar_api(api_key, api_secret):
    try:
        client = Client(api_key, api_secret)
        account_info = client.get_account()
        if account_info:
            print("✅ API validada correctamente.")
            return client
        else:
            print("❌ Error: no se pudo obtener la información de la cuenta. API o clave secreta inválida.")
            return None
    except binance.exceptions.BinanceAPIException as e:
        print(f"❌ Error al conectar con la API de Binance: {e}")
        return None

# Función para obtener el precio actual del par
def obtener_precio_actual(client, par):
    try:
        ticker = client.get_symbol_ticker(symbol=par.replace("/", ""))
        return float(ticker['price']) if 'price' in ticker else None
    except Exception as e:
        print(f"❌ Error al obtener el precio actual de {par}: {e}")
        return None

# Función para calcular la variación porcentual
def calcular_variacion_porcentual(precio_inicial, precio_actual):
    if precio_inicial == 0:
        return 0
    return ((precio_actual - precio_inicial) / precio_inicial) * 100

# Función para obtener la precisión y cantidad mínima de un par
def obtener_precision_y_minimo(client, par):
    try:
        exchange_info = client.get_symbol_info(par.replace("/", ""))
        if exchange_info:
            precision = exchange_info['quotePrecision']
            for filtro in exchange_info['filters']:
                if filtro['filterType'] == 'LOT_SIZE':
                    min_qty = float(filtro['minQty'])
                    return precision, min_qty
            print(f"❌ No se encontró la cantidad mínima para {par}.")
            return None, None
        else:
            print(f"❌ Error: no se pudo obtener información del par de trading {par}.")
            return None, None
    except Exception as e:
        print(f"❌ Error al obtener la precisión y cantidad mínima de {par}: {e}")
        return None, None

# Función para redondear la cantidad según la precisión del par
def redondear_cantidad(cantidad, precision):
    if precision is not None:
        return round(cantidad, precision)
    return cantidad

# Función para imprimir estadísticas de la sesión
def imprimir_estadisticas():
    global saldo_inicial, saldo_actual, operaciones_realizadas
    if not operaciones_realizadas:
        print("\n🔹 No se realizaron operaciones en esta sesión.")
        return

    print("\n🔹 Estadísticas de la sesión:")
    cantidad_comprada = sum(op['cantidad'] for op in operaciones_realizadas if op['tipo'] == 'compra')
    cantidad_vendida = sum(op['cantidad'] for op in operaciones_realizadas if op['tipo'] == 'venta')
    total_profit = sum(op['profit_usd'] for op in operaciones_realizadas if op['tipo'] == 'venta')
    total_loss = sum(op['loss_usd'] for op in operaciones_realizadas if op['tipo'] == 'compra')

    print(f"📊 Total comprado: {cantidad_comprada:.2f}")
    print(f"📊 Total vendido: {cantidad_vendida:.2f}")
    print(f"📈 Número de operaciones: {len(operaciones_realizadas)}")
    print(f"💰 Saldo inicial: {saldo_inicial:.2f} USD")
    print(f"💰 Saldo actual: {saldo_actual:.2f} USD")
    print(f"📈 Ganancias: {total_profit:.2f} USD ({(total_profit / saldo_inicial) * 100:.2f}%)")
    print(f"📉 Pérdidas: {total_loss:.2f} USD ({(total_loss / saldo_inicial) * 100:.2f}%)")

# Función para detener el bot y mostrar el resumen al hacer Ctrl+C
def manejar_interrupcion(signal, frame):
    print("\n⏹️ Bot detenido por el usuario.")
    imprimir_estadisticas()
    print("\nPresiona cualquier tecla para reiniciar el bot sin necesidad de ingresar la API y clave secreta.")
    input()  # Espera a que el usuario presione una tecla para reiniciar
    iniciar_bot()

# Función para monitorear los precios y ejecutar órdenes
def monitorear_precios(client, par, umbral_venta, umbral_compra, cantidad, usar_porcentaje, porcentaje_escalonado_venta, porcentaje_escalonado_compra, modo_operacion):
    global saldo_inicial, saldo_actual, operaciones_realizadas

    precio_inicial = obtener_precio_actual(client, par)
    if precio_inicial is None:
        print("❌ No se pudo obtener el precio inicial.")
        return

    print(f"🔄 Precio inicial de {par}: {precio_inicial:.8f}")

    precision, min_qty = obtener_precision_y_minimo(client, par)
    if precision is None or min_qty is None:
        print("❌ No se pudo obtener la precisión o cantidad mínima. Terminando el script.")
        return

    cantidad_redondeada = redondear_cantidad(cantidad, precision)
    if cantidad_redondeada < min_qty:
        print(f"❌ Error: la cantidad mínima para {par} es {min_qty:.{precision}f}.")
        return

    print(f"✅ Cantidad redondeada a la precisión del par: {cantidad_redondeada:.{precision}f}")

    saldo_inicial = precio_inicial * cantidad_redondeada
    saldo_actual = saldo_inicial

    ultima_orden = datetime.now()

    while True:
        try:
            precio_actual = obtener_precio_actual(client, par)
            if precio_actual is None:
                continue

            variacion_porcentual = calcular_variacion_porcentual(precio_inicial, precio_actual)

            print(f"📈 Precio actual: {precio_actual:.8f} (Variación: {variacion_porcentual:+.2f}%)")

            # Condiciones de compra si el modo es compra, mixto o ambos
            if (modo_operacion in ['compra', 'mixto'] and
                (usar_porcentaje and variacion_porcentual <= -umbral_compra) or
                (not usar_porcentaje and precio_actual <= precio_inicial - umbral_compra)):
                if datetime.now() - ultima_orden >= timedelta(seconds=60):
                    print(f"📉 Umbral de compra alcanzado.")
                    response = client.order_market_buy(
                        symbol=par.replace("/", ""),
                        quantity=cantidad_redondeada
                    )
                    print("✔️ Orden de compra ejecutada:", response)
                    ultima_orden = datetime.now()
                    precio_inicial = precio_actual
                    saldo_actual = precio_actual * cantidad_redondeada
                    operaciones_realizadas.append({'tipo': 'compra', 'cantidad': cantidad_redondeada, 'precio': precio_actual})

            # Condiciones de venta si el modo es venta, mixto o ambos
            if (modo_operacion in ['venta', 'mixto'] and
                (usar_porcentaje and variacion_porcentual >= umbral_venta) or
                (not usar_porcentaje and precio_actual >= precio_inicial + umbral_venta)):
                if datetime.now() - ultima_orden >= timedelta(seconds=60):
                    print(f"🚀 Umbral de venta alcanzado.")
                    response = client.order_market_sell(
                        symbol=par.replace("/", ""),
                        quantity=cantidad_redondeada
                    )
                    print("✔️ Orden de venta ejecutada:", response)
                    ultima_orden = datetime.now()
                    precio_inicial = precio_actual
                    saldo_actual = precio_actual * cantidad_redondeada
                    operaciones_realizadas.append({'tipo': 'venta', 'cantidad': cantidad_redondeada, 'precio': precio_actual})

            # Escalonado de operaciones de compra y venta si el modo lo permite
            if modo_operacion in ['compra', 'mixto'] and variacion_porcentual <= -porcentaje_escalonado_compra:
                if datetime.now() - ultima_orden >= timedelta(seconds=60):
                    print(f"📉 Escalón de compra alcanzado.")
                    response = client.order_market_buy(
                        symbol=par.replace("/", ""),
                        quantity=cantidad_redondeada
                    )
                    print("✔️ Orden de compra escalonada ejecutada:", response)
                    ultima_orden = datetime.now()
                    operaciones_realizadas.append({'tipo': 'compra', 'cantidad': cantidad_redondeada, 'precio': precio_actual})

            if modo_operacion in ['venta', 'mixto'] and variacion_porcentual >= porcentaje_escalonado_venta:
                if datetime.now() - ultima_orden >= timedelta(seconds=60):
                    print(f"🚀 Escalón de venta alcanzado.")
                    response = client.order_market_sell(
                        symbol=par.replace("/", ""),
                        quantity=cantidad_redondeada
                    )
                    print("✔️ Orden de venta escalonada ejecutada:", response)
                    ultima_orden = datetime.now()
                    operaciones_realizadas.append({'tipo': 'venta', 'cantidad': cantidad_redondeada, 'precio': precio_actual})

        except KeyboardInterrupt:
            # Captura de la señal Ctrl+C y muestra el resumen
            manejar_interrupcion(signal.SIGINT, None)

# Función para reiniciar el bot sin pedir API y clave secreta
def iniciar_bot():
    global api_key_global, api_secret_global

    signal.signal(signal.SIGINT, manejar_interrupcion)

    os.system('cls' if os.name == 'nt' else 'clear')  # Limpiar pantalla para una mejor visualización (Windows/Linux)

    if api_key_global is None or api_secret_global is None:
        api_key = getpass("🔐 Ingrese su API Key de Binance: ")
        api_secret = getpass("🔐 Ingrese su API Secret de Binance: ")
        api_key_global = api_key
        api_secret_global = api_secret
    else:
        print("🔐 Usando las credenciales guardadas.")

    client = validar_api(api_key_global, api_secret_global)
    if client is None:
        return

    par = input("🔗 Seleccione un par para operar (ejemplo: BTC/USDT): ").strip().upper()
    modo_operacion = input("⚙️ ¿El bot operará en solo compra, solo venta o trade mixto? (compra/venta/mixto): ").strip().lower()
    umbral_venta = float(input("💲 Umbral de venta (en %): "))
    umbral_compra = float(input("💲 Umbral de compra (en %): "))
    porcentaje_escalonado_venta = float(input("💲 Porcentaje de variación escalonada para venta: "))
    porcentaje_escalonado_compra = float(input("💲 Porcentaje de variación escalonada para compra: "))
    cantidad = float(input("🔢 Cantidad (en la moneda base del par): "))

    usar_porcentaje = True  # Configuración predeterminada para usar umbrales en porcentaje

    monitorear_precios(client, par, umbral_venta, umbral_compra, cantidad, usar_porcentaje, porcentaje_escalonado_venta, porcentaje_escalonado_compra, modo_operacion)

# Ejecutar bot
if __name__ == "__main__":
    iniciar_bot()
