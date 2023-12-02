#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import binascii
import logging
import logging.handlers
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import paho.mqtt.client as mqtt
import serial

logging.getLogger().setLevel('DEBUG')
logging.info('Starting Viessmann2mqtt')

MQTT_USER = "clientabc123"
MQTT_PASSWORD = "publicabc123"
MQTT_SERVER = '3.73.129.80'
MQTT_TOPIC = 'Viessmann/'  # should end with /
hostName = ""
serverPort = 443

CMD_VREAD = binascii.unhexlify('F7')
CMD_VWRITE = binascii.unhexlify('F4')

STYLE = '''
    div {
    }
    div span {
        font-weight: bold;
    }
'''

WRITE_COMMAND = None


def connecthandler(mqc, userdata, flags, rc):
    logging.info("Connected to MQTT broker with rc=%d" % rc)
    mqc.publish(MQTT_TOPIC + "connected", True, qos=1, retain=True)


def disconnecthandler(mqc, userdata, rc):
    logging.warning("Disconnected from MQTT broker with rc=%d" % rc)


class MyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global WRITE_COMMAND

        if self.path != '/':
            try:
                WRITE_COMMAND = write_commands[self.path]
            except:
                pass
            self.send_response(307)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(bytes("<html>"
                                   "<head>"
                                   "<title>KW1</title>"
                                   "<meta http-equiv='refresh' content='30'>"
                                   "<style>%s</style>"
                                   "</head>\n" % STYLE, "utf-8"))
            self.wfile.write(bytes("<p>Request: %s</p>\n" % self.path, "utf-8"))
            self.wfile.write(bytes("<body>\n", "utf-8"))
            self.wfile.write(bytes("<div>Partymodus <a href='/party_on'>AN</a>|<a href='/party_off'>AUS</a></div>\n", "utf-8"))
            self.wfile.write(bytes("<div>Modus <a href='/mod_ww'>Warm Wasser</a>|<a href='/mod_all'>Alles An</a></div>\n", "utf-8"))
            for cmd in stat_commands:
                self.wfile.write(bytes("<div>%s: <span>%s</span></div>\n" % (cmd.desc, cmd.res), "utf-8"))
            self.wfile.write(bytes("</body></html>\n", "utf-8"))


def startServer():
    webServer = HTTPServer((hostName, serverPort), MyServer)
    print("Server started http://%s:%s" % (hostName, serverPort))
    webServer.serve_forever()


def main():
    thread1 = Thread(target=startLoop)
    thread2 = Thread(target=startServer, daemon=True)

    thread1.start()
    thread2.start()
    print("Started deamons")


def startLoop():
    print("Connecting...")
    ser = serial.Serial(
        port='/dev/ttyUSB0',
        baudrate=4800,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_TWO,
        bytesize=serial.EIGHTBITS,
        xonxoff=False,
        exclusive=True
    )
    mqc = mqtt.Client()
    mqc.username_pw_set(username=MQTT_USER, password=MQTT_PASSWORD)
    mqc.on_connect = connecthandler
    mqc.on_disconnect = disconnecthandler
    mqc.will_set(MQTT_TOPIC + "connected", False, qos=2, retain=True)
    mqc.disconnected = True
    mqc.connect(MQTT_SERVER, 1883, 60)
    mqc.loop_start()
    print("Connected")

    while True:
        loop(ser, stat_commands, mqc)
        ser.timeout = 5
        ser.read(100)
    # print("Done!")


def loop(ser, commands, mqc):
    global WRITE_COMMAND
    print("Waiting for ACK")
    ser.timeout = 3

    try:
        if ser.read(1) == binascii.unhexlify('05'):
            # print("Got ACK")
            ser.write(binascii.unhexlify('01'))
            for cmd in commands:
                command(ser, cmd)
            if WRITE_COMMAND is not None:
                command(ser, WRITE_COMMAND)
                WRITE_COMMAND = None
    except Exception as e:
        logging.error("Unhandled error serial [" + str(e) + "]")

    try:
        print('Sending metrics')

        for cmd in commands:
            resultJSON = '{"' + cmd.name + '":"' + str(cmd.res) + '"}'
            mqc.publish(MQTT_TOPIC + 'status/json', resultJSON, qos=0, retain=True)
    except Exception as e:
        logging.error("Unhandled error mqtt [" + str(e) + "]")


def command(ser, cmd):
    # print("Execute command", cmd.name)
    ser.write(cmd.protocmd)
    # print("Proto", cmd.protocmd)
    ser.write(cmd.address)
    # print("Address", cmd.address)
    ser.write(cmd.length.to_bytes(1, 'big'))
    ser.timeout = 1
    if cmd.protocmd == CMD_VREAD:
        # print("Now reading", cmd.length)
        val = ser.read(cmd.length)
        # print('OptoLink < %s' % binascii.hexlify(val))
        cmd.res = convertunit(cmd.unit, val)
        # print('Command %s returned %s' % (cmd.name, cmd.res))
    elif cmd.protocmd == CMD_VWRITE:
        ser.write(cmd.res)
        if ser.read(1) == binascii.unhexlify('00'):
            pass # print('Command %s wrote %s' % (cmd.name, cmd.res))
        else:
            pass # print('Error in write command %s %s' % (cmd.name, cmd.res))


def errorcode(errorcode):
    errorcode_VScotHO1_72 = {
        0x00: "Anlage ohne Fehler",
        0x0F: "Wartung durchführen",
        0x10: "Kurzschluss Außentemperatursensor",
        0x18: "Unterbrechung Außentemperatursensor",
        0x19: "Fehler externer Außentemperatursensor (Anschlusserweiterung ATS1)",
        0x1D: "Störung Volumenstromsensor (STRS1)",
        0x1E: "Störung Volumenstromsensor (STRS1)",
        0x1F: "Störung Volumenstromsensor (STRS1)",
        0x20: "Kurzschluss Vorlaufsensor Anlage",
        0x28: "Unterbrechung Vorlaufsensor Anlage",
        0x30: "Kurzschluss Kesseltemperatursensor",
        0x38: "Unterbrechung Kesseltemperatursensor",
        0x40: "Kurzschluss Vorlaufsensor HK2",
        0x41: "Rücklauftemperatur HK2 Kurzschluss",
        0x44: "Kurzschluss Vorlaufsensor HK3",
        0x45: "Rücklauftemperatur HK3 Kurzschluss",
        0x48: "Unterbrechung Vorlaufsensor HK2",
        0x49: "Rücklauftemperatur HK2 Unterbrechung",
        0x4C: "Unterbrechung Vorlaufsensor HK3",
        0x4D: "Rücklauftemperatur HK3 Unterbrechung",
        0x50: "Kurzschluss Speichertemperatursensor / Komfortsensor / Ladesensor",
        0x51: "Kurzschluss Auslauftemperatursensor",
        0x58: "Unterbrechung Speichertemperatursensor/ Komfortsensor/ Ladesensor",
        0x59: "Unterbrechung Auslauftemperatursensor",
        0x90: "Solarmodul: Kurzschluss Sensor 7",
        0x91: "Solarmodul: Kurzschluss Sensor 10",
        0x92: "Solarregelung: Kurzschluss Kollektortemp.Sensor",
        0x93: "Solarregelung: Kurzschluss Kollektorrücklauf-Sensor",
        0x94: "Solarregelung: Kurzschluss Speichertemp.Sensor",
        0x98: "Solarmodul: Unterbrechung Sensor 7",
        0x99: "Solarmodul: Unterbrechung Sensor 10",
        0x9A: "Solar: Unterbrech. Kollektortemp.Sensor",
        0x9B: "Vitosolic: Unterbrech. Kollektorrücklauf",
        0x9C: "Solar: Unterbrech. Speichertemp.Sensor",
        0x9E: "Solarmodul: Delta-T Überwachung",
        0x9F: "Solarregelung: allgemeiner Fehler ",
        0xA2: "Fehler niedriger Wasserdruck Regelung",
        0xA3: "Abgastemperatursensor gesteckt",
        0xA4: "Überschreitung Anlagenmaximaldruck",
        0xA6: "Fehler Fremdstromanode nicht in Ordnung",
        0xA7: "Fehler Uhrenbaustein Bedienteil ",
        0xA8: "Interne Pumpe meldet Luft",
        0xA9: "Interne Pumpe blockiert",
        0xB0: "Kurzschluss Abgastemperatursensor",
        0xB1: "Fehler Bedienteil",
        0xB4: "interner Fehler Temperaturmessung",
        0xB5: "interner Fehler EEPROM",
        0xB7: "Kesselcodierkarte falsch/fehlerhaft",
        0xB8: "Unterbrechung Abgastemperatursensor",
        0xB9: "Fehlerhafte Übertragung Codiersteckerdaten",
        0xBA: "Kommunikationsfehler Mischer HK2",
        0xBB: "Kommunikationsfehler Mischer HK3",
        0xBC: "Fehler Fernbedienung HK1",
        0xBD: "Fehler Fernbedienung HK2",
        0xBE: "Fehler Fernbedienung HK3",
        0xBF: "LON-Modul falsch/fehlerhaft",
        0xC1: "Kommunikationsfehler Anschl.Erw. EA1",
        0xC2: "Kommunikationsfehler Solarregelung",
        0xC3: "Kommunikationsfehler Anschl.Erw. AM1",
        0xC4: "Kommunikationsfehler Anschl.Erw. OT",
        0xC5: "Fehler Drehzahlgeregelte Pumpe - Interne Pumpe",
        0xC6: "Fehler Drehzahlgeregelte Pumpe Heizkreis 2",
        0xC7: "Fehler Drehzahlgeregelte Pumpe Heizkreis 1",
        0xC8: "Fehler Drehzahlgeregelte Pumpe Heizkreis 3",
        0xC9: "Komm.-fehler KM-Bus Gerät DAP1",
        0xCA: "Komm.-fehler KM-Bus Gerät DAP2",
        0xCD: "Kommunikationsfehler Vitocom 100",
        0xCE: "Kommunikationsfehler Anschlußerweiterung extern",
        0xCF: "Kommunikationsfehler LON-Modul",
        0xD1: "Brennerstörung",
        0xD6: "Störung Digitaler Eingang 1",
        0xD7: "Störung Digitaler Eingang 2",
        0xD8: "Störung Digitaler Eingang 3",
        0xDA: "Kurzschluss Raumtemperatursensor HK1",
        0xDB: "Kurzschluss Raumtemperatursensor HK2",
        0xDC: "Kurzschluss Raumtemperatursensor HK3",
        0xDD: "Unterbrechung Raumtemperatursensor HK1",
        0xDE: "Unterbrechung Raumtemperatursensor HK2",
        0xDF: "Unterbrechung Raumtemperatursensor HK3",
        0xE0: "Fehler externer Teilnehmer LON",
        0xE1: "SCOT Kalibrationswert Grenzverletzung O",
        0xE2: "Keine Kalibration wg mangelnder Strömung",
        0xE3: "Kalibrationsfehler thermisch",
        0xE4: "Fehler in Spannungsversorgung 24V - Feuerungsautomat",
        0xE5: "Fehler Flammenverstärker - Feuerungsautomat",
        0xE6: "Min. Luft-/Wasserdruck nicht erreicht",
        0xE7: "SCOT Kalibrationswert Grenzverletzung U",
        0xE8: "SCOT Ionisationssignal weicht ab",
        0xEA: "SCOT Kalibrationswert abw. von Vorgänger",
        0xEB: "SCOT Kalibration nicht ausgeführt",
        0xEC: "SCOT Ionisationssollwert fehlerhaft",
        0xED: "SCOT Systemfehler",
        0xEE: "Keine Flammbildung",
        0xEF: "Flammenausfall in Sicherheitszeit",
        0xF0: "Kommunikationsfehler zum Feuerungsatomat",
        0xF1: "Abgastemperaturbegrenzer ausgelöst",
        0xF2: "TB ausgelöst - Übertemperatur",
        0xF3: "Flammenvortäuschung",
        0xF4: "Keine Flammenbildung",
        0xF5: "Fehler Luftdruckwächter",
        0xF6: "Fehler Gasdruckschalter",
        0xF7: "Fehler Luftdruckschalter",
        0xF8: "Fehler Gasventil",
        0xF9: "Fehler Gebläse - Drehzahl nicht erreicht",
        0xFA: "Fehler Gebläse - Stillstand nicht erreicht",
        0xFB: "Flammenausfall im Betrieb",
        0xFC: "Fehler in der elektrischen Ansteuerung der Gasarmatur",
        0xFD: "Interner Fehler Feuerungsautomat",
        0xFE: "Vorwarnung Wartung fällig (Warnung) ",
        0xFF: "Fehler Feuerungsautomat ohne eigenen Fehlercode",
    }
    if errorcode in errorcode_VScotHO1_72:
        return errorcode_VScotHO1_72[errorcode]
    return 'errorcode_%02x' % errorcode


# STate ReTurnstatus COunter CS/3600
def convertunit(unit, value):
    if unit == 'deviceType':
        if value == binascii.unhexlify('2094'):
            return 'V200 KW1'
    if unit == 'UT':
        return int.from_bytes(value, "little", signed=True) / 10
    if unit == 'ST':
        return int.from_bytes(value, "little")
    if unit == 'RT':
        return int.from_bytes(value, "little")
    if unit == 'CO':
        return int.from_bytes(value, "little")
    if unit == 'CS':
        return int.from_bytes(value, "little") / 3600
    if unit == 'BA':
        if value == binascii.unhexlify('00'):
            return 'Warm Wasser'
        if value == binascii.unhexlify('01'):
            return 'Reduziert'
        if value == binascii.unhexlify('02'):
            return 'Normal'
        if value == binascii.unhexlify('03'):
            return 'Heizung und Warm Wasser'
        if value == binascii.unhexlify('04'):
            return 'Heizung und Warmwasser'
        if value == binascii.unhexlify('05'):
            return 'Abgeschaltet'
    return 'error'


class Command:
    def __init__(self, name, protocmd, address, length, unit, desc, res='NA'):
        self.name = name
        self.protocmd = protocmd
        self.address = binascii.unhexlify(address)
        self.length = length
        self.unit = unit
        self.desc = desc
        self.res = res


write_commands = {
    "/party_on": Command("setBetriebPartyM1", CMD_VWRITE, '2303', 1, 'RT', 'Partymodus', binascii.unhexlify('01')),
    "/party_off": Command("setBetriebPartyM1", CMD_VWRITE, '2303', 1, 'RT', 'Partymodus', binascii.unhexlify('00')),
    "/mod_ww": Command("setBetriebsArt", CMD_VWRITE, '2301', 1, 'BA', 'Modus', binascii.unhexlify('00')),
    "/mod_all": Command("setBetriebsArt", CMD_VWRITE, '2301', 1, 'BA', 'Modus', binascii.unhexlify('04')),
    "/ww_60": Command("setTempWWsoll", CMD_VWRITE, '6300', 1, 'ST', 'Warmwasser Soll 60', int.to_bytes(60,2,"little")),
    "/ww_55": Command("setTempWWsoll", CMD_VWRITE, '6300', 1, 'ST', 'Warmwasser Soll 55', int.to_bytes(55,2,"little")),
    "/ww_50": Command("setTempWWsoll", CMD_VWRITE, '6300', 1, 'ST', 'Warmwasser Soll 50', int.to_bytes(50,2,"little")),
    "/ww_45": Command("setTempWWsoll", CMD_VWRITE, '6300', 1, 'ST', 'Warmwasser Soll 45', int.to_bytes(45,2,"little")),
}

stat_commands = [
    # Command("deviceType",CMD_VREAD,'00F8',2,'deviceType'),
    Command("getBetriebsArt", CMD_VREAD, '2301', 1, 'BA', 'Modus'),  # operation mode
    Command("getBetriebPartyM1", CMD_VREAD, '2303', 1, 'RT', 'Partymodus'),  # operation mode
    # Command("getBetriebPartyM2", CMD_VREAD, '3303', 1, 'RT', 'Partymodus M2'),  # operation mode
    Command("getTempPartyM1", CMD_VREAD, '2308', 1, 'ST', 'Partytemperatur'),  # operation mode
    # Command("getTempPartyM2", CMD_VREAD, '3308', 1, 'ST', 'Partytemperatur M2'),  # operation mode
    Command("getTempA", CMD_VREAD, '0800', 2, 'UT', 'Aussentemperatur'),  # out temperature
    Command("getTempWWist", CMD_VREAD, '0804', 2, 'UT', 'Warmwasser Ist'),  # warm water temperature
    Command("getTempWWsoll", CMD_VREAD, '6300', 1, 'ST', 'Warmwasser Soll'),  # warm water target
    Command("getTempKist", CMD_VREAD, '0802', 2, 'UT', 'Heizkessel Ist'),  # kessel temperature
    Command("getTempKsoll", CMD_VREAD, '5502', 2, 'UT', 'Heizkessel Soll'),  # kessel target
    Command("getTempRaumsoll", CMD_VREAD, '2306', 1, 'ST', 'Raumsoll'),  # room temperature target
    Command("getBrennerStatus", CMD_VREAD, '551E', 1, 'RT', 'Brennerstatus'),  # burner state
    Command("getBrennerStarts", CMD_VREAD, '088A', 2, 'CO', 'Brenner Starts'),  # burner starts
    Command("getBrennerStunden1", CMD_VREAD, '08A7', 4, 'CS', 'Brennstunden I'),  # burner hours lvl 1
    Command("getBrennerStunden2", CMD_VREAD, '08AB', 4, 'CS', 'Brennstunden II'),  # burner hours lvl 2
    Command("getPumpeStatusM1", CMD_VREAD, '2906', 1, 'RT', 'Heizpumpe'),  # heater pump
    Command("getPumpeTankStatus", CMD_VREAD, '0845', 1, 'RT', 'Speicherpumpe'),  # store/collector pump
    Command("getPumpeZStatus", CMD_VREAD, '0846', 1, 'RT', 'Zirkulationspumpe'),  # zirkulation pump
    Command("getStatusStoerung", CMD_VREAD, '7579', 1, 'RT', 'Stoerung'),  # errors
    Command("getBrennerStoerung", CMD_VREAD, '0883', 1, 'RT', 'Brenner Fehler'),  # burner errors

    # Command("getExhaustTemp", CMD_VREAD, '0808', 2, 'UT'),  # abgas temp
    # Command("getBackwardTemp", CMD_VREAD, '080A', 2, 'UT'),  # ruecklauf temp
    # Command("getBackwardM2Temp", CMD_VREAD, '3902', 2, 'UT'),  # ruecklauf temp
    # Command("getForwardTemp", CMD_VREAD, '080C', 2, 'UT'),  # vorlauf temp
    # Command("getForwardM2Temp", CMD_VREAD, '3900', 2, 'UT'),  # vorlauf temp
    # Command("getExhaustLowTemp", CMD_VREAD, '5525', 2, 'UT'),  # exhaust low temp
    # Command("getTempAAvr", CMD_VREAD, '5527', 2, 'UT'),  # exhaust avr temp

]

main()
