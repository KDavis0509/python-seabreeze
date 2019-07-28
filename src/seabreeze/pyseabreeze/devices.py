"""


"""
import itertools
import struct
import time

from future.utils import with_metaclass
from seabreeze.pyseabreeze.exceptions import SeaBreezeError
from seabreeze.pyseabreeze.communication import USBCommBase, USBCommOOI, USBCommOBP
from seabreeze.pyseabreeze import features as sbfeatures

# spectrometer models for pyseabreeze
#
VENDOR_ID = 0x2457
# NOTE: PRODUCT_IDS and _model_registry will be filled
#       via the SeaBreezeDevice metaclass below
PRODUCT_IDS = set()
_model_class_registry = {}


def is_ocean_optics_usb_device(dev):
    """return if the provided device is a supported ocean optics device

    Parameters
    ----------
    dev : usb.core.Device

    Returns
    -------
    bool
    """
    # noinspection PyUnresolvedReferences
    return dev.idVendor == VENDOR_ID and dev.idProduct in PRODUCT_IDS


class _SeaBreezeDeviceMeta(type):
    """metaclass for pyseabreeze devices"""

    def __new__(cls, name, bases, attr_dict):
        if name != 'SeaBreezeDevice':
            # > the command interface
            _interface_cls = attr_dict['interface_cls']
            assert issubclass(_interface_cls, USBCommBase), "instance class does not derive from USBCommBase"

            # make the seabreeze device derive from the interface_cls
            bases = tuple(b for b in itertools.chain(bases, [_interface_cls]))

        return super(_SeaBreezeDeviceMeta, cls).__new__(cls, name, bases, attr_dict)

    def __init__(cls, name, bases, attr_dict):
        if name != 'SeaBreezeDevice':
            # check if required class attributes are present and correctly typed
            # > product_id
            _product_id = attr_dict['product_id']
            assert isinstance(_product_id, int), "product_od not an int"
            assert 0 <= _product_id <= 0xFFFF, "product_id not a 16bit int"
            assert _product_id not in PRODUCT_IDS, "product_id already registered"
            # > usb endpoint map
            _endpoint_map = attr_dict['endpoint_map']
            assert isinstance(_endpoint_map, _EndPointMap), "no endpoint map provided"
            # > model name
            _model_name = attr_dict['model_name']
            assert isinstance(_model_name, str), "model name not a str"

            # add to the class registry
            PRODUCT_IDS.add(_product_id)
            _model_class_registry[_product_id] = cls

        super(_SeaBreezeDeviceMeta, cls).__init__(name, bases, attr_dict)


class _EndPointMap(object):
    """internal endpoint map for spectrometer classes"""
    def __init__(self, ep_out=None, lowspeed_in=None, highspeed_in=None, highspeed_in2=None):
        self.primary_out = self.ep_out = ep_out
        self.primary_in = self.lowspeed_in = lowspeed_in
        self.secondary_out = ep_out
        self.secondary_in = self.highspeed_in = highspeed_in
        self.secondary_in2 = self.highspeed_in2 = highspeed_in2


class _DarkPixelRanges(tuple):
    """internal dark pixel range class"""
    def __new__(cls, *ranges):
        dp = itertools.chain(*(range(low, high) for (low, high) in ranges))
        return super(_DarkPixelRanges, cls).__new__(_DarkPixelRanges, dp)


class _TriggerMode(object):
    """internal trigger modes class"""
    NORMAL = 0x00
    SOFTWARE = 0x01
    LEVEL = 0x01
    SYNCHRONIZATION = 0x02
    HARDWARE = 0x03
    EDGE = 0x03
    SINGLE_SHOT = 0x04
    SELF_NORMAL = 0x80
    SELF_SOFTWARE = 0x81
    SELF_SYNCHRONIZATION = 0x82
    SELF_HARDWARE = 0x83
    DISABLED = 0xFF
    OBP_NORMAL = 0x00
    OBP_EXTERNAL = 0x01
    OBP_INTERNAL = 0x02


class SeaBreezeDevice(with_metaclass(_SeaBreezeDeviceMeta)):

    # attributes have to be defined in derived classes
    product_id = None
    model_name = None
    endpoint_map = None
    interface_cls = None

    # internal attribute
    _serial_number = '?'
    _cached_features = None

    def __new__(cls, handle=None):
        if handle is None:
            raise SeaBreezeError("Don't instantiate SeaBreezeDevice directly. Use `SeabreezeAPI.list_devices()`.")
        specialized_cls = _model_class_registry[handle.idProduct]
        return super(SeaBreezeDevice, cls).__new__(specialized_cls, handle)

    def __init__(self, handle=None):
        if handle is None:
            raise SeaBreezeError("Don't instantiate SeaBreezeDevice directly. Use `SeabreezeAPI.list_devices()`.")
        self.handle = handle
        try:
            self._serial_number = self.get_serial_number()
        except SeaBreezeError:
            pass

    @property
    def model(self):
        return self.model_name

    @property
    def serial_number(self):
        return self._serial_number

    def __repr__(self):
        return "<SeaBreezeDevice %s:%s>" % (self.model, self.serial_number)

    def open(self):
        """open the spectrometer usb connection

        Returns
        -------
        None
        """
        self.open_device(self.handle)
        if issubclass(self.interface_cls, USBCommOOI):
            # initialize the spectrometer
            self.usb_send(struct.pack('<B', 0x01))
            time.sleep(0.1)  # wait shortly after init command
        # cache features
        self._cached_features = {}
        _ = self.features
        # get serial
        self._serial_number = self.get_serial_number()

    def close(self):
        """close the spectrometer usb connection

        Returns
        -------
        None
        """
        self.close_device()

    @property
    def is_open(self):
        """returns if the spectrometer device usb connection is opened

        Returns
        -------
        bool
        """
        return self._is_open()

    def get_serial_number(self):
        """return the serial number string of the spectrometer

        Returns
        -------
        serial_number: str
        """
        try:
            if issubclass(self.interface_cls, USBCommOOI):
                # The serial is stored in slot 0
                return str(self.f.eeprom.eeprom_read_slot(0))

            elif issubclass(self.interface_cls, USBCommOBP):
                return self.query(0x00000100, "")

            else:
                raise NotImplementedError("No serial number for interface class %s" % str(self.interface_cls))
        except AttributeError:
            raise SeaBreezeError("device not open")

    def get_model(self):
        """return the model string of the spectrometer

        Returns
        -------
        model: str
        """
        return self.model_name

    @property
    def features(self):
        """return a dictionary of all supported features

        this returns a dictionary with all supported Features of the spectrometer

        Returns
        -------
        features : `dict` [`str`, `seabreeze.cseabreeze.SeaBreezeFeature`]
        """
        # TODO: make this a cached property
        if not self._cached_features:
            self._cached_features = {k: [] for k in sbfeatures.SeaBreezeFeature.get_feature_class_registry()}
            for feature_cls in self.feature_classes:
                f_list = self._cached_features.setdefault(feature_cls.identifier, [])
                f_list.append(feature_cls(self, len(f_list)))
        return self._cached_features

    @property
    def f(self):
        """convenience access to features via attributes

        this allows you to access a feature like this::

            # via .features
            device.features['spectrometer'][0].get_intensities()
            # via .f
            device.f.spectrometer.get_intensities()

        """
        class FeatureAccessHandler(object):
            def __init__(self, feature_dict):
                for identifier, features in feature_dict.items():
                    setattr(self, identifier, features[0] if features else None)  # TODO: raise FeatureNotAvailable?
        return FeatureAccessHandler(self.features)


# SPECTROMETER DEFINITIONS
# ========================
#
class USB2000PLUS(SeaBreezeDevice):

    # communication config
    product_id = 0x101E
    model_name = 'USB2000PLUS'
    interface_cls = USBCommOOI
    endpoint_map = _EndPointMap(ep_out=0x01, lowspeed_in=0x81, highspeed_in=0x82, highspeed_in2=0x86)

    # spectrometer config
    dark_pixel_indices = _DarkPixelRanges((6, 21))  # as in seabreeze-3.0.9
    integration_time_min = 1000
    integration_time_max = 655350000
    integration_time_base = 1
    spectrum_num_pixel = 2048
    spectrum_raw_length = (2048 * 2) + 1
    spectrum_max_value = 65535
    trigger_modes = ('NORMAL', 'SOFTWARE', 'SYNCHRONIZATION', 'HARDWARE')

    # features
    feature_classes = (
        sbfeatures.eeprom.SeaBreezeEEPromFeatureOOI,
        sbfeatures.spectrometer.SeaBreezeSpectrometerFeatureUSB2000PLUS,
        sbfeatures.rawusb.SeaBreezeRawUSBAccessFeature,
    )


class USB2000(SeaBreezeDevice):

    # communication config
    product_id = 0x1002
    model_name = 'USB2000'
    interface_cls = USBCommOOI
    endpoint_map = _EndPointMap(ep_out=0x02, lowspeed_in=0x87, highspeed_in=0x82)

    # spectrometer config
    dark_pixel_indices = _DarkPixelRanges((2, 24))
    integration_time_min = 3000
    integration_time_max = 655350000
    integration_time_base = 1000
    spectrum_num_pixel = 2048
    spectrum_raw_length = (2048 * 2) + 1
    spectrum_max_value = 4095
    trigger_modes = ('NORMAL', 'SOFTWARE', 'HARDWARE')

    # features
    feature_classes = (
        sbfeatures.eeprom.SeaBreezeEEPromFeatureOOI,
        sbfeatures.spectrometer.SeaBreezeSpectrometerFeatureUSB2000,
        sbfeatures.rawusb.SeaBreezeRawUSBAccessFeature,
    )


class HR2000(SeaBreezeDevice):

    # communication config
    product_id = 0x100a
    model_name = 'HR2000'
    interface_cls = USBCommOOI
    endpoint_map = _EndPointMap(ep_out=0x02, lowspeed_in=0x87, highspeed_in=0x82)

    # spectrometer config
    dark_pixel_indices = _DarkPixelRanges((2, 24))
    integration_time_min = 3000
    integration_time_max = 655350000
    integration_time_base = 1000
    spectrum_num_pixel = 2048
    spectrum_raw_length = (2048 * 2) + 1
    spectrum_max_value = 4095
    trigger_modes = ('NORMAL', 'SOFTWARE', 'HARDWARE')

    # features
    feature_classes = (
        sbfeatures.eeprom.SeaBreezeEEPromFeatureOOI,
        sbfeatures.spectrometer.SeaBreezeSpectrometerFeatureHR2000,
        sbfeatures.rawusb.SeaBreezeRawUSBAccessFeature,
    )


class HR4000(SeaBreezeDevice):

    # communication config
    product_id = 0x1012
    model_name = 'HR4000'
    interface_cls = USBCommOOI
    endpoint_map = _EndPointMap(ep_out=0x01, lowspeed_in=0x81, highspeed_in=0x82, highspeed_in2=0x86)

    # spectrometer config
    dark_pixel_indices = _DarkPixelRanges((2, 13))
    integration_time_min = 10
    integration_time_max = 655350000
    integration_time_base = 1
    spectrum_num_pixel = 3840
    spectrum_raw_length = (3840 * 2) + 1
    spectrum_max_value = 16383
    trigger_modes = ('NORMAL', 'SOFTWARE', 'SYNCHRONIZATION', 'HARDWARE')

    # features
    feature_classes = (
        sbfeatures.eeprom.SeaBreezeEEPromFeatureOOI,
        sbfeatures.spectrometer.SeaBreezeSpectrometerFeatureHR4000,
        sbfeatures.rawusb.SeaBreezeRawUSBAccessFeature,
    )


class HR2000PLUS(SeaBreezeDevice):

    # communication config
    product_id = 0x1016
    model_name = 'HR2000PLUS'
    interface_cls = USBCommOOI
    endpoint_map = _EndPointMap(ep_out=0x01, lowspeed_in=0x81, highspeed_in=0x82, highspeed_in2=0x86)

    # spectrometer config
    dark_pixel_indices = _DarkPixelRanges((2, 24))
    integration_time_min = 1000
    integration_time_max = 655350000
    integration_time_base = 1
    spectrum_num_pixel = 2048
    spectrum_raw_length = (2048 * 2) + 1
    spectrum_max_value = 16383
    trigger_modes = ('NORMAL', 'SOFTWARE', 'SYNCHRONIZATION', 'HARDWARE')

    # features
    feature_classes = (
        sbfeatures.eeprom.SeaBreezeEEPromFeatureOOI,
        sbfeatures.spectrometer.SeaBreezeSpectrometerFeatureHR2000PLUS,
        sbfeatures.rawusb.SeaBreezeRawUSBAccessFeature,
    )




"""

class USB650(SpectrometerFeatureUSB650,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['USB650']
    _PIXELS = 2048  # FIXME
    _RAW_SPECTRUM_LEN = (2048 * 2) + 1
    _INTEGRATION_TIME_MIN = 3000
    _INTEGRATION_TIME_MAX = 655350000
    _INTEGRATION_TIME_BASE = 1000
    _MAX_PIXEL_VALUE = 4095

class QE65000(SpectrometerFeatureQE65000,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             ThermoElectricFeatureOOI,
             NoShutterFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['QE65000']
    _PIXELS = 1280  # FIXME
    _RAW_SPECTRUM_LEN = (1024 + 256)*2 + 1
    _INTEGRATION_TIME_MIN = 8000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1000
    _MAX_PIXEL_VALUE = 65535

class USB2000PLUS(SpectrometerFeatureUSB2000PLUS,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['USB2000PLUS']
    _PIXELS = 2048  # FIXME
    _RAW_SPECTRUM_LEN = (2048 * 2) + 1
    _INTEGRATION_TIME_MIN = 1000
    _INTEGRATION_TIME_MAX = 655350000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535

class USB4000(SpectrometerFeatureUSB4000,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['USB4000']
    _PIXELS = 3840  # FIXME
    _RAW_SPECTRUM_LEN = (3840 * 2) + 1
    _INTEGRATION_TIME_MIN = 10
    _INTEGRATION_TIME_MAX = 655350000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535

class NIRQUEST512(SpectrometerFeatureNIRQUEST512,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             ThermoElectricFeatureOOI,
             NoShutterFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['NIRQUEST512']
    _PIXELS = 512  # FIXME
    _RAW_SPECTRUM_LEN = (512 * 2) + 1
    _INTEGRATION_TIME_MIN = 1000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1000
    _MAX_PIXEL_VALUE = 65535

class NIRQUEST256(SpectrometerFeatureNIRQUEST256,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             ThermoElectricFeatureOOI,
             NoShutterFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['NIRQUEST256']
    _PIXELS = 256  # FIXME
    _RAW_SPECTRUM_LEN = (256 * 2) + 1
    _INTEGRATION_TIME_MIN = 1000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1000
    _MAX_PIXEL_VALUE = 65535

class MAYA2000PRO(SpectrometerFeatureMAYA2000PRO,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['MAYA2000PRO']
    _PIXELS = 2304  # FIXME
    _RAW_SPECTRUM_LEN = (2304 * 2) + 1
    _INTEGRATION_TIME_MIN = 7200
    _INTEGRATION_TIME_MAX = 65000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 64000

class MAYA2000(SpectrometerFeatureMAYA2000,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['MAYA2000']
    _PIXELS = 2304  # FIXME
    _RAW_SPECTRUM_LEN = (2304 * 2) + 1
    _INTEGRATION_TIME_MIN = 15000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535

class TORUS(SpectrometerFeatureTORUS,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['TORUS']
    _PIXELS = 2048  # FIXME
    _RAW_SPECTRUM_LEN = (2048 * 2) + 1
    _INTEGRATION_TIME_MIN = 1000
    _INTEGRATION_TIME_MAX = 655350000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535

class APEX(SpectrometerFeatureAPEX,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['APEX']
    _PIXELS = 2304  # FIXME
    _RAW_SPECTRUM_LEN = (2304 * 2) + 1
    _INTEGRATION_TIME_MIN = 15000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 64000

class MAYALSL(SpectrometerFeatureMAYALSL,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['MAYALSL']
    _PIXELS = 2304  # FIXME
    _RAW_SPECTRUM_LEN = (2304 * 2) + 1
    _INTEGRATION_TIME_MIN = 7200
    _INTEGRATION_TIME_MAX = 65000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 64000

class JAZ(SpectrometerFeatureJAZ,
             WavelengthCoefficientsEEPromFeature,
             NonlinearityCoefficientsEEPromFeature,
             EEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['JAZ']
    _PIXELS = 2048  # FIXME
    _RAW_SPECTRUM_LEN = (2048 * 2)  # XXX: No Sync byte!
    _INTEGRATION_TIME_MIN = 1000
    _INTEGRATION_TIME_MAX = 655350000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535

class STS(SpectrometerFeatureSTS,
             NonlinearityCoefficientsOBPFeature,
             SpectrumProcessingFeatureOBP,
             NoEEPromFeature,
             NoShutterFeature,
             NoTecFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['STS']
    _PIXELS = 1024  # FIXME
    _RAW_SPECTRUM_LEN = (1024 * 2)  # XXX: No Sync byte!
    _INTEGRATION_TIME_MIN = 10
    _INTEGRATION_TIME_MAX = 85000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 16383

class QEPRO(SpectrometerFeatureQEPRO,
             ThermoElectricFeatureOBP,
             NonlinearityCoefficientsOBPFeature,
             NoEEPromFeature,
             NoShutterFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['QEPRO']
    _PIXELS = 1044  # FIXME
    _RAW_SPECTRUM_LEN = (1044 * 4) + 32  # XXX: Metadata
    _INTEGRATION_TIME_MIN = 10000
    _INTEGRATION_TIME_MAX = 1600000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = (2**18)-1

class VENTANA(SpectrometerFeatureVENTANA,
             ThermoElectricFeatureOBP,
             NonlinearityCoefficientsOBPFeature,
             NoEEPromFeature,
             NoShutterFeature,
             NotImplementedWrapper):
    _ENDPOINT_MAP = EndPoints['VENTANA']
    _PIXELS = 1024  # FIXME
    _RAW_SPECTRUM_LEN = (1024 * 2)  # XXX: No Sync byte!
    _INTEGRATION_TIME_MIN = 22000
    _INTEGRATION_TIME_MAX = 60000000
    _INTEGRATION_TIME_BASE = 1
    _MAX_PIXEL_VALUE = 65535


"""
