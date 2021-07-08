import os
import breads.utils as utils
from warnings import warn

class Instrument:
    def __init__(self, ins_type):
        self.ins_type = ins_type
        assert self.check_instrument_type(), "Instrument Not Implemented Yet"
        self.wavelengths = None
        self.data = None
        self.noise = None
        self.bad_pixels = None
        self.bary_RV = None
        self.refpos = [0,0]
        
    def check_instrument_type(self):
        implemented = self.instruments_implemented()
        if self.ins_type in implemented:
            return True
        print("Instruments Implemented Yet:", implemented)
        return False
    
    def instruments_implemented(self):
        files = os.listdir(utils.file_directory(__file__))
        implemented = []
        for file in files:
            if ".py" in file and "instrument" not in file:
                implemented += [file[:file.index(".py")]]
        return implemented
    
    def manual_data_entry(self, wavelengths, data, noise, bad_pixels, bary_RV):
        warn("when feeding data manually, ensure correct units. wavelengths in microns, bary_RV in km/s")
        self.wavelengths = wavelengths
        self.data = data
        self.noise = noise
        self.bad_pixels = bad_pixels
        self.bary_RV = bary_RV # in km/s
        self.valid_data_check()
    
    def read_data(self, filename):
        print("Instruments Implemented Yet:", self.instruments_implemented())
        raise NotImplementedError(
            "Import derived class corresponding to your instrument. You are currently using the base class.")
        
    def valid_data_check(self):
        assert self.data.ndim == 3, "Data must be 3-dimensional"
        assert self.wavelengths.ndim == 1, "Wavelength Array must be 1-dimensional"
        assert self.data.shape[0] == self.wavelengths.shape[0], \
                        "Wavelength dimension of the spaxel data must be equal to size to wavelength array"
        assert self.noise is None or self.noise.shape == self.data.shape, \
                            "If present, noise must be of same shape as spaxel data"
        assert self.bad_pixels is None or self.bad_pixels.shape == self.data.shape, \
                            "If present, bad pixel must be of same shape as spaxel data"
     
    