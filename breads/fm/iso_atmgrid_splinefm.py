import numpy as np

from scipy.interpolate import InterpolatedUnivariateSpline
from astropy import constants as const

from  scipy.interpolate import interp1d
from PyAstronomy import pyasl

from breads.utils import get_spline_model

def pixgauss2d(p, shape, hdfactor=10, xhdgrid=None, yhdgrid=None):
    """
    2d gaussian model. Documentation to be completed. Also faint of t
    """
    A, xA, yA, w, bkg = p
    ny, nx = shape
    if xhdgrid is None or yhdgrid is None:
        xhdgrid, yhdgrid = np.meshgrid(np.arange(hdfactor * nx).astype(np.float) / hdfactor,
                                       np.arange(hdfactor * ny).astype(np.float) / hdfactor)
    else:
        hdfactor = xhdgrid.shape[0] // ny
    gaussA_hd = A / (2 * np.pi * w ** 2) * np.exp(
        -0.5 * ((xA - xhdgrid) ** 2 + (yA - yhdgrid) ** 2) / w ** 2)
    gaussA = np.nanmean(np.reshape(gaussA_hd, (ny, hdfactor, nx, hdfactor)), axis=(1, 3))
    return gaussA + bkg


def iso_atmgrid_splinefm(nonlin_paras, cubeobj, atm_grid=None, atm_grid_wvs=None, transmission=None,boxw=1, psfw=1.2,nodes=20,badpixfraction=0.75,loc=None):
    """
    For characterization of isolated objects, so no speckle.
    Generate forward model fitting the continuum with a spline. No high pass filter or continuum normalization here.
    Fitting for a grid of atmospheric models.
    The spline are defined with a linear model. Each spaxel (if applicable) is independently modeled which means the
    number of linear parameters increases as N_nodes*boxw^2+1.

    Args:
        nonlin_paras: Non-linear parameters of the model, which are first the parameters defining the atmopsheric grid
            (atm_grid). The following parameters are the spin (vsini), the radial velocity, and the position (if loc is
            not defined) of the planet in the FOV.
                [atm paras ....,vsini,rv,y,x] for 3d cubes (e.g. OSIRIS)
                [atm paras ....,vsini,rv,y] for 2d (e.g. KPIC, y being fiber)
                [atm paras ....,vsini,rv] for 1d spectra
        cubeobj: Data object.
            Must inherit breads.instruments.instrument.Instrument.
        atm_grid: Planet atmospheric model grid as a scipy.interpolate.RegularGridInterpolator object. Make sure the
            wavelength coverage of the grid is just right and not too big as it will slow down the spin broadening.
        atm_grid_wvs: Wavelength sampling on which atm_grid is defined. Wavelength needs to be uniformly sampled.
        transmission: Transmission spectrum (tellurics and instrumental).
            np.ndarray of size the number of wavelength bins.
        boxw: size of the stamp to be extracted and modeled around the (x,y) location of the planet.
            Must be odd. Default is 1.
        psfw: Width (sigma) of the 2d gaussian used to model the planet PSF. This won't matter if boxw=1 however.
        nodes: If int, number of nodes equally distributed. If list, custom locations of nodes [x1,x2,..].
            To model discontinous functions, use a list of list [[x1,...],[xn,...]].
        badpixfraction: Max fraction of bad pixels in data.
        loc: (x,y) position of the planet for spectral cubes, or fiber position (y position) for 2d data.
            When loc is not None, the x,y non-linear parameters should not be given.


    Returns:
        d: Data as a 1d vector with bad pixels removed (no nans)
        M: Linear model as a matrix of shape (Nd,Np) with bad pixels removed (no nans). Nd is the size of the data
            vector and Np = N_nodes*boxw^2+1 is the number of linear parameters.
        s: Noise vector (standard deviation) as a 1d vector matching d.
    """
    Natmparas = len(atm_grid.values.shape)-1
    atm_paras = [p for p in nonlin_paras[0:Natmparas]]
    other_nonlin_paras = nonlin_paras[Natmparas::]

    # Handle the different data dimensions
    # Convert everything to 3D cubes (wv,y,x) for the followying
    if len(cubeobj.data.shape)==1:
        data = cubeobj.data[:,None,None]
        noise = cubeobj.noise[:,None,None]
        bad_pixels = cubeobj.bad_pixels[:,None,None]
    elif len(cubeobj.data.shape)==2:
        data = cubeobj.data[:,:,None]
        noise = cubeobj.noise[:,:,None]
        bad_pixels = cubeobj.bad_pixels[:,:,None]
    elif len(cubeobj.data.shape)==3:
        data = cubeobj.data
        noise = cubeobj.noise
        bad_pixels = cubeobj.bad_pixels
    if cubeobj.refpos is None:
        refpos = [0,0]
    else:
        refpos = cubeobj.refpos

    vsini,rv = other_nonlin_paras[0:2]
    # Defining the position of companion
    # If loc is not defined, then the x,y position is assume to be a non linear parameter.
    if np.size(loc) ==2:
        x,y = loc
    elif np.size(loc) ==1 and loc is not None:
        x,y = 0,loc
    elif loc is None:
        if len(cubeobj.data.shape)==1:
            x,y = 0,0
        elif len(cubeobj.data.shape)==2:
            x,y = 0,other_nonlin_paras[2]
        elif len(cubeobj.data.shape)==3:
            x,y = other_nonlin_paras[3],other_nonlin_paras[2]

    nz, ny, nx = data.shape

    if len(cubeobj.wavelengths.shape)==1:
        wvs = cubeobj.wavelengths[:,None,None]
    elif len(cubeobj.wavelengths.shape)==2:
        wvs = cubeobj.wavelengths[:,:,None]
    elif len(cubeobj.wavelengths.shape)==3:
        wvs = cubeobj.wavelengths
    _, nywv, nxwv = wvs.shape

    if boxw % 2 == 0:
        raise ValueError("boxw, the width of stamp around the planet, must be odd in splinefm().")
    if boxw > ny or boxw > nx:
        raise ValueError("boxw cannot be bigger than the data in splinefm().")

    # remove pixels that are bad in the transmission or the star spectrum
    bad_pixels[np.where(np.isnan(transmission))[0],:,:] = np.nan

    # Extract stamp data cube cropping at the edges
    w = int((boxw - 1) // 2)
    # right, left  = np.min([l+w+1,nx]), np.max([l-w,0])
    # top, bottom = np.min([k+w+1,ny]), np.max([k-w,0])
    _paddata =np.pad(data,[(0,0),(w,w),(w,w)],mode="constant",constant_values = np.nan)
    _padnoise =np.pad(noise,[(0,0),(w,w),(w,w)],mode="constant",constant_values = np.nan)
    _padbad_pixels =np.pad(bad_pixels,[(0,0),(w,w),(w,w)],mode="constant",constant_values = np.nan)
    k, l = int(np.round(refpos[1] + y)), int(np.round(refpos[0] + x))
    dx,dy = x-l,y-k
    k,l = k+w,l+w
    d = np.ravel(_paddata[:, k-w:k+w+1, l-w:l+w+1])
    s = np.ravel(_padnoise[:, k-w:k+w+1, l-w:l+w+1])
    badpixs = np.ravel(_padbad_pixels[:, k-w:k+w+1, l-w:l+w+1])
    badpixs[np.where(s==0)] = np.nan


    # manage all the different cases to define the position of the spline nodes
    if type(nodes) is int:
        N_nodes = nodes
        x_knots = np.linspace(np.min(wvs), np.max(wvs), N_nodes, endpoint=True).tolist()
    elif type(nodes) is list  or type(nodes) is np.ndarray :
        x_knots = nodes
        if type(nodes[0]) is list or type(nodes[0]) is np.ndarray :
            N_nodes = np.sum([np.size(n) for n in nodes])
        else:
            N_nodes = np.size(nodes)
    else:
        raise ValueError("Unknown format for nodes.")

    fitback = False
    if fitback:
        N_linpara = N_nodes + 3*boxw**2
    else:
        N_linpara = N_nodes

    where_finite = np.where(np.isfinite(badpixs))
    if np.size(where_finite[0]) <= (1-badpixfraction) * np.size(badpixs) or vsini < 0:
        # don't bother to do a fit if there are too many bad pixels
        return np.array([]), np.array([]).reshape(0,N_linpara), np.array([])
    else:

        planet_model = atm_grid(atm_paras)[0]

        if np.sum(np.isnan(planet_model)) >= 1 or np.sum(planet_model)==0 or np.size(atm_grid_wvs) != np.size(planet_model):
            return np.array([]), np.array([]).reshape(0,N_linpara), np.array([])
        else:
            if vsini != 0:
                spinbroad_model = pyasl.fastRotBroad(atm_grid_wvs, planet_model, 0.1, vsini)
            else:
                spinbroad_model = planet_model
            planet_f = interp1d(atm_grid_wvs,spinbroad_model, bounds_error=False, fill_value=0)

        lwvs = wvs[:,np.clip(k-2*w,0,nywv-1),np.clip(l-2*w,0,nxwv-1)]
        # Get the linear model (ie the matrix) for the spline
        M_spline = get_spline_model(x_knots, lwvs, spline_degree=3)

        if fitback:
            M_background = np.zeros((nz, boxw, boxw, boxw, boxw,3))
            for m in range(boxw):
                for n in range(boxw):
                    lwvs = wvs[:,np.clip(k-2*w+m,0,nywv-1),np.clip(l-2*w+m,0,nxwv-1)]
                    M_background[:, m, n, m, n, 0] = 1
                    M_background[:, m, n, m, n, 1] = lwvs
                    M_background[:, m, n, m, n, 2] = lwvs**2
            M_background = np.reshape(M_background, (nz, boxw, boxw, 3*boxw**2))

        psfs = np.zeros((nz, boxw, boxw))
        # Technically allows super sampled PSF to account for a true 2d gaussian integration of the area of a pixel.
        # But this is disabled for now with hdfactor=1.
        hdfactor = 1#5
        xhdgrid, yhdgrid = np.meshgrid(np.arange(hdfactor * (boxw)).astype(np.float) / hdfactor,
                                       np.arange(hdfactor * (boxw)).astype(np.float) / hdfactor)
        psfs += pixgauss2d([1., w+dx, w+dy, psfw, 0.], (boxw, boxw), xhdgrid=xhdgrid, yhdgrid=yhdgrid)[None, :, :]
        psfs = psfs / np.nansum(psfs, axis=(1, 2))[:, None, None]

        # The planet spectrum model is RV shifted and multiplied by the tranmission
        planet_spec = transmission * planet_f(wvs * (1 - (rv - cubeobj.bary_RV) / const.c.to('km/s').value))
        # Go from a 1d spectrum to the 3D scaled PSF
        scaled_psfs = np.zeros((nz,boxw,boxw,N_nodes))+np.nan
        for _k in range(boxw):
            for _l in range(boxw):
                lwvs = wvs[:,np.clip(k-2*w+_k,0,nywv-1),np.clip(l-2*w+_l,0,nxwv-1)]
                planet_spec = transmission * planet_f(lwvs * (1 - (rv - cubeobj.bary_RV) / const.c.to('km/s').value))
                scaled_psfs[:,_k,_l,:] = psfs[:, _k,_l,None] * M_spline * planet_spec[:,None]

        # combine planet model with speckle model
        if fitback:
            M = np.concatenate([scaled_psfs[:, :, :, None],M_background], axis=3)
        else:
            M = np.concatenate([scaled_psfs[:, :, :, None]], axis=3)
        # Ravel data dimension
        M = np.reshape(M, (nz * boxw * boxw, N_linpara))
        # Get rid of bad pixels
        sr = s[where_finite]
        dr = d[where_finite]
        Mr = M[where_finite[0], :]

        return dr, Mr, sr