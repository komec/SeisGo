#define key classes
import os
import obspy
import pyasdf
from obspy.core import Trace
import numpy as np
import matplotlib.pyplot as plt
from obspy.io.sac.sactrace import SACTrace
from obspy.signal.filter import bandpass
from scipy.fftpack import fft,ifft,fftfreq,next_fast_len
from seispy import utils
######
class Station(object):
    """
    Container for basic station information. Doesn't intend to replace the inventory class in ObsPy.

    Attributes
    -----------
    net: network name
    sta: station name
    loc: location code
    lon: longitude
    lat: latitude
    ele: elevation
    """
    def __init__(self, net=None,sta=None,loc=None,chan=None,lon=None, lat=None, ele=None):
        self.net = net
        self.sta = sta
        self.loc = loc
        self.chan = chan
        self.lon = lon
        self.lat = lat
        self.ele = ele

    def __str__(self):
        """
        Display key content of the object.
        """
        print("network      :   "+str(self.net))
        print("station      :   "+str(self.sta))
        print("location     :   "+str(self.loc))
        print("channel      :   "+str(self.chan))
        print("longitude   :   "+str(self.lon))
        print("latitude    :   "+str(self.lat))
        print("elevation   :   "+str(self.ele))

        print("")

        return "<Station object>"

class FFTData(object):
    """
    Object to FFT data. The idea of having a FFTData data type
    was originally designed by Tim Clements for SeisNoise.jl (https://github.com/tclements/SeisNoise.jl).
    """
    def __init__(self,trace:obspy.core.Trace,inc_hours,cc_len_secs,cc_step_secs,stainv=None,
                     freqmin=None,freqmax=None,time_norm='no',freq_norm='no',smooth=20,
                     data=None,misc=dict()):
        """
        Initialize the object. Will do whitening if specicied in freq_norm.
        """
        if stainv is not None:
            self.sta,self.net,self.lon,self.lat,self.ele,self.loc = utils.sta_info_from_inv(stainv)
        else:
            self.net=trace[0].stats.network
            self.sta=trace[0].stats.station
            self.lon=0.0
            self.lat=0.0
            self.ele=0.0
            self.loc=''

        self.chan=trace[0].stats.channel
        self.dt = 1/trace[0].stats.sampling_rate
        self.sps  = int(trace[0].stats.sampling_rate)
        self.freqmin=freqmin
        self.freqmax=freqmax
        self.time_norm=time_norm
        self.freq_norm=freq_norm
        self.smooth=smooth
        self.inc_hours=inc_hours
        self.cc_len_secs=cc_len_secs
        self.cc_step_secs=cc_step_secs
        self.misc=misc

        fft_white=[]
        # cut daily-long data into smaller segments (dataS always in 2D)
        trace_stdS,dataS_t,dataS = utils.slicing_trace(trace,cc_len_secs,cc_step_secs)        # optimized version:3-4 times faster

        self.std=trace_stdS
        self.time=dataS_t
        Nfft=0
        if len(dataS)>0:
            #------to normalize in time or not------
            if time_norm != 'no':
                if time_norm == 'one_bit': 	# sign normalization
                    white = np.sign(dataS)
                elif time_norm == 'rma': # running mean: normalization over smoothed absolute average
                    white = np.zeros(shape=dataS.shape,dtype=dataS.dtype)
                    for kkk in range(N):
                        white[kkk,:] = dataS[kkk,:]/utils.moving_ave(np.abs(dataS[kkk,:]),smooth)

            else:	# don't normalize
                white = dataS

            #-----to whiten or not------
            Nfft = int(next_fast_len(int(dataS.shape[1])))
            if white.ndim == 1:
                axis = 0
            elif white.ndim == 2:
                axis = 1
            fft_white = fft(white, Nfft, axis=axis) # return FFT

        ##
        self.data=fft_white
        self.Nfft=Nfft

        if len(dataS)>0 and freq_norm != 'no' and freqmin is not None:
            print('Initializing FFTData with whitening ...')
            self.whiten()  # whiten and return FFT

    ##### method for whitening
    def whiten(self):
        """
        Whiten FFTData
        """
        freq_norm=self.freq_norm
        if self.freqmin is None:
            raise ValueError('freqmin has to be specified as an attribute in FFTData!')

        if self.freqmax is None:
            self.freqmax=0.499*self.sps
            print('freqmax not specified, use default as 0.499*samp_freq.')

        if self.data.ndim == 1:
            axis = 0
        elif self.data.ndim == 2:
            axis = 1

        Nfft = int(self.Nfft)

        Napod = 100
        freqVec = fftfreq(Nfft, d=self.dt)[:Nfft // 2]
        J = np.where((freqVec >= self.freqmin) & (freqVec <= self.freqmax))[0]
        low = J[0] - Napod
        if low <= 0:
            low = 1

        left = J[0]
        right = J[-1]
        high = J[-1] + Napod
        if high > Nfft/2:
            high = int(Nfft//2)

        FFTRawSign = self.data
        # Left tapering:
        if axis == 1:
            FFTRawSign[:,0:low] *= 0
            FFTRawSign[:,low:left] = np.cos(
                np.linspace(np.pi / 2., np.pi, left - low)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[:,low:left]))
            # Pass band:
            if freq_norm == 'phase_only':
                FFTRawSign[:,left:right] = np.exp(1j * np.angle(FFTRawSign[:,left:right]))
            elif freq_norm == 'rma':
                for ii in range(self.data.shape[0]):
                    tave = moving_ave(np.abs(FFTRawSign[ii,left:right]),self.smooth_N)
                    FFTRawSign[ii,left:right] = FFTRawSign[ii,left:right]/tave
            # Right tapering:
            FFTRawSign[:,right:high] = np.cos(
                np.linspace(0., np.pi / 2., high - right)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[:,right:high]))
            FFTRawSign[:,high:Nfft//2] *= 0

            # Hermitian symmetry (because the input is real)
            FFTRawSign[:,-(Nfft//2)+1:] = np.flip(np.conj(FFTRawSign[:,1:(Nfft//2)]),axis=axis)
        else:
            FFTRawSign[0:low] *= 0
            FFTRawSign[low:left] = np.cos(
                np.linspace(np.pi / 2., np.pi, left - low)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[low:left]))
            # Pass band:
            if freq_norm == 'phase_only':
                FFTRawSign[left:right] = np.exp(1j * np.angle(FFTRawSign[left:right]))
            elif freq_norm == 'rma':
                tave = moving_ave(np.abs(FFTRawSign[left:right]),self.smooth_N)
                FFTRawSign[left:right] = FFTRawSign[left:right]/tave
            # Right tapering:
            FFTRawSign[right:high] = np.cos(
                np.linspace(0., np.pi / 2., high - right)) ** 2 * np.exp(
                1j * np.angle(FFTRawSign[right:high]))
            FFTRawSign[high:Nfft//2] *= 0

            # Hermitian symmetry (because the input is real)
            FFTRawSign[-(Nfft//2)+1:] = FFTRawSign[1:(Nfft//2)].conjugate()[::-1]


        ##re-assign back to self.data.
        self.data=FFTRawSign


class CorrData(object):
    """
    Object to store cross-correlation data. The idea of having a CorrData data type
    was originally designed by Tim Clements for SeisNoise.jl (https://github.com/tclements/SeisNoise.jl).
    The CorrData class in SeisPy differrs from that in SeisNoise by adding the internal methods
    for merging, plotting, and saving.
    ======= Attributes ======
    net=[None,None],sta=[None,None],loc=[None,None],chan=[None,None],lon=[None,None],
    lat=[None,None],ele=[None,None],cc_comp=None,
    lag=None,dt=None,dist=None,ngood=None,time=None,data=None,substack:bool=False
    misc=dict().

    misc is a dictionary that stores additional parameters.

    ======= Methods ======
    append(): Merges to objects.
    to_sac(): convert and save to sac file, using obspy SACTrace object.
    plot(): simple plotting function to display the cross-correlation data.
    """
    def __init__(self,net=[None,None],sta=[None,None],loc=[None,None],chan=[None,None],\
                    lon=[None,None],lat=[None,None],ele=[None,None],cc_comp=None,lag=None,\
                    dt=None,dist=None,az=None,baz=None,ngood=None,time=None,data=None,\
                    substack:bool=False,misc=dict()):
        self.net=net
        self.sta=sta
        self.loc=loc
        self.chan=chan
        self.lon=lon
        self.lat=lat
        self.ele=ele
        self.cc_comp=cc_comp
        self.lag=lag
        self.dt=dt
        self.dist=dist
        self.az=az
        self.baz=baz
        self.ngood=ngood
        self.time=time
        self.data=data
        self.substack=substack
        self.misc=misc

    def __str__(self):
        """
        Display key content of the object.
        """
        print("network      :   "+str(self.net))
        print("station      :   "+str(self.sta))
        print("location     :   "+str(self.loc))
        print("channel      :   "+str(self.chan))
        print("longitudes   :   "+str(self.lon))
        print("latitudes    :   "+str(self.lat))
        print("elevations   :   "+str(self.ele))
        print("cc_comp      :   "+self.cc_comp)
        print("maxlag       :   "+str(self.lag))
        print("delta        :   "+str(self.dt))
        print("dist (km)    :   "+str(self.dist))
        print("ngood        :   "+str(self.ngood))
        print("time         :   "+str(obspy.UTCDateTime(self.time)))
        print("substack     :   "+str(self.substack))
        print("data         :   "+str(self.data.shape))
        print(str(self.data))
        print("")

        return "<CorrData object>"

    def append(self,c):
        """
        Append will merge new object. The idea is to merge multiple sets of CorrData at
        different time chunks. Therefore, this function will merge the following attributes only:
        <ngood>,<time>,<data>

        **Note: substack will be set to True after merging, regardless the value in the original object.**
        """
        if not self.substack:
            self.ngood=np.reshape(self.ngood,(1,1))
            self.time=np.reshape(self.time,(1,1))
            self.data=np.reshape(self.data,(1,self.data.shape[0]))

        if not c.substack:
            c.ngood=np.reshape(c.ngood,(1,1))
            c.time=np.reshape(c.time,(1,1))
            c.data=np.reshape(c.data,(1,c.data.shape[0]))

        self.ngood =np.concatenate((self.ngood,c.ngood))
        self.time=np.concatenate((self.time,c.time))
        self.data=np.concatenate((self.data,c.data),axis=0)

        self.substack=True

    def to_asdf(self,file,v=True):
        """
        Save CorrData object too asdf file.
        """
        cc_comp = self.cc_comp
        # source-receiver pair
        netsta_pair = self.net[0]+'.'+self.sta[0]+'_'+\
                        self.net[1]+'.'+self.sta[1]
        chan_pair = self.chan[0]+'_'+self.chan[1]

        #save to asdf
        lonS,lonR = self.lon
        latS,latR = self.lat
        eleS,eleR = self.ele

        if "cc_method" in list(self.misc.keys()):
            cc_method = self.misc['cc_method']
        else:
            cc_method = ''

        parameters = {'dt':self.dt,
            'maxlag':np.float32(self.lag),
            'dist':np.float32(self.dist/1000),
            'azi':np.float32(self.az),
            'baz':np.float32(self.baz),
            'lonS':np.float32(lonS),
            'latS':np.float32(latS),
            'eleS':np.float32(eleS),
            'lonR':np.float32(lonR),
            'latR':np.float32(latR),
            'eleR':np.float32(eleR),
            'ngood':self.ngood,
            'cc_method':cc_method,
            'time':self.time,
            'substack':self.substack,
            'comp':self.cc_comp}

        with pyasdf.ASDFDataSet(file,mpi=False) as ccf_ds:
            ccf_ds.add_auxiliary_data(data=self.data, data_type=netsta_pair, path=chan_pair, parameters=parameters)
        if v: print('CorrData saved to: '+file)


    def to_sac(self,outdir='.',file=None,v=True):
        """
        Save CorrData object to sac file.
        """
        try:
            if not os.path.isdir(outdir):os.makedirs(outdir)
        except Exception as e:
            print(e)

        slon,rlon=self.lon
        slat,rlat=self.lat
        sele,rele=self.ele

        if not self.substack:
            corrtime=obspy.UTCDateTime(self.time)
            nzyear=corrtime.year
            nzjday=corrtime.julday
            nzhour=corrtime.hour
            nzmin=corrtime.minute
            nzsec=corrtime.second
            nzmsec=corrtime.microsecond
            if file is None:
                file=str(corrtime).replace(':', '-')+'_'+self.cc_comp+'.sac'
            sac = SACTrace(nzyear=nzyear,nzjday=nzjday,nzhour=nzhour,nzmin=nzmin,nzsec=nzsec,nzmsec=nzmsec,
                           b=-self.lag,delta=self.dt,stla=rlat,stlo=rlon,stel=sele,evla=slat,evlo=slon,evdp=rele,
                           evel=rele,dist=self.dist,az=self.az,baz=self.baz,data=self.data)

            sacfile  = os.path.join(outdir,file)
            sac.write(sacfile,byteorder='big')
            if v: print('saved sac to: '+sacfile)
        else:
            nwin=self.data.shape[0]
            for i in range(nwin):
                corrtime=obspy.UTCDateTime(self.time[i])
                nzyear=corrtime.year
                nzjday=corrtime.julday
                nzhour=corrtime.hour
                nzmin=corrtime.minute
                nzsec=corrtime.second
                nzmsec=corrtime.microsecond
                if file is None:
                    file=str(corrtime).replace(':', '-')+'_'+self.cc_comp+'.sac'
                sac = SACTrace(nzyear=nzyear,nzjday=nzjday,nzhour=nzhour,nzmin=nzmin,nzsec=nzsec,nzmsec=nzmsec,
                               b=-self.lag,delta=self.dt,stla=rlat,stlo=rlon,stel=sele,evla=slat,evlo=slon,evdp=rele,
                               evel=rele,dist=self.dist,az=self.az,baz=self.baz,data=self.data[i,:])

                sacfile  = os.path.join(outdir,file)
                sac.write(sacfile,byteorder='big')
                if v: print('saved sac to: '+sacfile)

    def plot(self,freqmin=None,freqmax=None,lag=None,save=False,figdir=None,figsize=(10,8)):
        """
        Plotting method for CorrData. It is the same as seispy.plotting.plot_corrdata(), with exactly the same arguments.
        Display the 2D matrix of the cross-correlation functions for a certain time-chunck.
        PARAMETERS:
        --------------------------
        freqmin: min frequency to be filtered
        freqmax: max frequency to be filtered
        lag: time ranges for display
        """
        # open data for read
        if save:
            if figdir==None:print('no path selected! save figures in the default path')

        netstachan1 = self.net[0]+'.'+self.sta[0]+'.'+self.loc[0]+'.'+self.chan[0]
        netstachan2 = self.net[1]+'.'+self.sta[1]+'.'+self.loc[1]+'.'+self.chan[1]

        dt,maxlag,dist,ngood,ttime,substack = [self.dt,self.lag,self.dist,self.ngood,self.time,self.substack]

       # lags for display
        if not lag:lag=maxlag
        if lag>maxlag:raise ValueError('lag excceds maxlag!')
        lag0=np.min([1.0*lag,maxlag])

        # t is the time labels for plotting
        if lag>=5:
            tstep=int(int(lag)/5)
            t1=np.arange(-int(lag),0,step=tstep);t2=np.arange(0,int(lag+0.5*tstep),step=tstep)
            t=np.concatenate((t1,t2))
        else:
            tstep=lag/5
            t1=np.arange(-lag,0,step=tstep);t2=np.arange(0,lag+0.5*tstep,step=tstep)
            t=np.concatenate((t1,t2))

        indx1 = int((maxlag-lag0)/dt);indx2 = indx1+2*int(lag0/dt)+1

        # cc matrix
        if substack:
            data = self.data[:,indx1:indx2]
            timestamp = np.empty(ttime.size,dtype='datetime64[s]')
            # print(data.shape)
            nwin = data.shape[0]
            amax = np.zeros(nwin,dtype=np.float32)
            if nwin==0 or len(ngood)==1:
                print('continue! no enough trace to plot!')
                return

            tmarks = []
            data_normalizd=data

            # load cc for each station-pair
            for ii in range(nwin):
                if freqmin is not None and freqmax is not None:
                    data[ii] = bandpass(data[ii],freqmin,freqmax,1/dt,corners=4, zerophase=True)
                data[ii] = data[ii]-np.mean(data[ii])
                amax[ii] = np.max(np.abs(data[ii]))
                data_normalizd[ii] = data[ii]/amax[ii]
                timestamp[ii] = obspy.UTCDateTime(ttime[ii])
                tmarks.append(obspy.UTCDateTime(ttime[ii]).strftime('%Y-%m-%dT%H:%M:%S'))

            dstack_mean=np.mean(data,axis=0)
    #         dstack_robust=stack.robust_stack(data)[0]

            # plotting
            if nwin>10:
                tick_inc = int(nwin/5)
            else:
                tick_inc = 2

            fig = plt.figure(figsize=figsize)
            ax = fig.add_subplot(6,1,(1,4))
            ax.matshow(data_normalizd,cmap='seismic',extent=[-lag0,lag0,nwin,0],aspect='auto')
            ax.plot((0,0),(nwin,0),'k-')
            if freqmin is not None and freqmax is not None:
                ax.set_title('%s-%s : dist : %5.2f km : %4.2f-%4.2f Hz' % (netstachan1,netstachan2,
                                                                           dist,freqmin,freqmax))
            else:
                ax.set_title('%s-%s : dist : %5.2f km : unfiltered' % (netstachan1,netstachan2,dist))
            ax.set_xlabel('time [s]')
            ax.set_xticks(t)
            ax.set_yticks(np.arange(0,nwin,step=tick_inc))
            ax.set_yticklabels(tmarks[0:nwin:tick_inc])
            ax.set_xlim([-lag,lag])
            ax.xaxis.set_ticks_position('bottom')

            ax1 = fig.add_subplot(6,1,(5,6))
            if freqmin is not None and freqmax is not None:
                ax1.set_title('stack at %4.2f-%4.2f Hz'%(freqmin,freqmax))
            else:
                ax1.set_title('stack: unfiltered')
            tstack=np.arange(-lag0,lag0+0.5*dt,dt)
            if len(tstack)>len(dstack_mean):tstack=tstack[:-1]
            ax1.plot(tstack,dstack_mean,'b-',linewidth=1,label='mean')
    #         ax1.plot(tstack,dstack_robust,'r-',linewidth=1,label='robust')
            ax1.set_xlabel('time [s]')
            ax1.set_xticks(t)
            ax1.set_xlim([-lag,lag])
            ylim=ax1.get_ylim()
            ax1.plot((0,0),ylim,'k-')

            ax1.set_ylim(ylim)
            ax1.legend(loc='upper right')
            ax1.grid()

            fig.tight_layout()
        else: #only one trace available
            data = self.data[indx1:indx2]

            # load cc for each station-pair
            if freqmin is not None and freqmax is not None:
                data = bandpass(data,freqmin,freqmax,1/dt,corners=4, zerophase=True)
            data = data-np.mean(data)
            amax = np.max(np.abs(data))
            data /= amax
            timestamp = obspy.UTCDateTime(ttime)
            tmarks=obspy.UTCDateTime(ttime).strftime('%Y-%m-%dT%H:%M:%S')

            tx=np.arange(-lag0,lag0+0.5*dt,dt)
            if len(tx)>len(data):tx=tx[:-1]
            plt.figure(figsize=figsize)
            ax=plt.gca()
            plt.plot(tx,data,'k-',linewidth=1)
            if freqmin is not None and freqmax is not None:
                plt.title('%s-%s : dist : %5.2f km : %4.2f-%4.2f Hz' % (netstachan1,netstachan2,
                                                                           dist,freqmin,freqmax))
            else:
                plt.title('%s-%s : dist : %5.2f km : unfiltered' % (netstachan1,netstachan2,dist))
            plt.xlabel('time [s]')
            plt.xticks(t)
            ylim=ax.get_ylim()
            plt.plot((0,0),ylim,'k-')

            plt.ylim(ylim)
            plt.xlim([-lag,lag])
            ax.grid()

        # save figure or just show
        if save:
            if figdir==None:figdir = sfile.split('.')[0]
            if not os.path.isdir(figdir):os.mkdir(figdir)
            outfname = figdir+\
            '/{0:s}_{1:s}_{2:s}-{3:s}Hz.png'.format(netstachan1,netstachan2,
                                                             str(freqmin),str(freqmax))
            plt.savefig(outfname, format='png', dpi=300)
            print('saved to: '+outfname)
            plt.close()
        else:
            plt.show()

class Power(object):
    """
    Container for power spectra for each component, with any shape

    Attributes
    ----------
    c11 : :class:`~numpy.ndarray`
        Power spectral density for component 1 (any shape)
    c22 : :class:`~numpy.ndarray`
        Power spectral density for component 2 (any shape)
    cZZ : :class:`~numpy.ndarray`
        Power spectral density for component Z (any shape)
    cPP : :class:`~numpy.ndarray`
        Power spectral density for component P (any shape)
    """

    def __init__(spectra, c11=None, c22=None, cZZ=None, cPP=None, window=None,
                overlap=None,freq=None):
        spectra.c11 = c11
        spectra.c22 = c22
        spectra.cZZ = cZZ
        spectra.cPP = cPP
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq


class Cross(object):
    """
    Container for cross-power spectra for each component pairs, with any shape

    Attributes
    ----------
    c12 : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and 2 (any shape)
    c1Z : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and Z (any shape)
    c1P : :class:`~numpy.ndarray`
        Cross-power spectral density for components 1 and P (any shape)
    c2Z : :class:`~numpy.ndarray`
        Cross-power spectral density for components 2 and Z (any shape)
    c2P : :class:`~numpy.ndarray`
        Cross-power spectral density for components 2 and P (any shape)
    cZP : :class:`~numpy.ndarray`
        Cross-power spectral density for components Z and P (any shape)
    """

    def __init__(spectra, c12=None, c1Z=None, c1P=None, c2Z=None, c2P=None,
                 cZP=None, window=None,overlap=None,freq=None):
        spectra.c12 = c12
        spectra.c1Z = c1Z
        spectra.c1P = c1P
        spectra.c2Z = c2Z
        spectra.c2P = c2P
        spectra.cZP = cZP
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq


class Rotation(object):
    """
    Container for rotated spectra, with any shape

    Attributes
    ----------
    cHH : :class:`~numpy.ndarray`
        Power spectral density for rotated horizontal component H (any shape)
    cHZ : :class:`~numpy.ndarray`
        Cross-power spectral density for components H and Z (any shape)
    cHP : :class:`~numpy.ndarray`
        Cross-power spectral density for components H and P (any shape)
    coh : :class:`~numpy.ndarray`
        Coherence between horizontal components
    ph : :class:`~numpy.ndarray`
        Phase of cross-power spectrum between horizontal components
    direc :: class: `~numpy.ndarray`
        All directions considered when computing the coh and ph.
    tilt : float
        Angle (azimuth) of tilt axis
    admt_value : : class :`~numpy.ndarray`
        Admittance between rotated horizontal at the tilt direction and vertical.
    coh_value : float
        Maximum coherence
    phase_value : float
        Phase at maximum coherence
    """

    def __init__(spectra, cHH=None, cHZ=None, cHP=None, coh=None, ph=None,direc=None,
                 tilt=None, admt_value=None,coh_value=None, phase_value=None,
                 window=None,overlap=None,freq=None):
        spectra.cHH = cHH
        spectra.cHZ = cHZ
        spectra.cHP = cHP
        spectra.coh = coh
        spectra.ph = ph
        spectra.direc = direc
        spectra.tilt = tilt
        spectra.admt_value = admt_value
        spectra.coh_value = coh_value
        spectra.phase_value = phase_value
        # spectra.angle = angle
        spectra.window = window
        spectra.overlap = overlap
        spectra.freq = freq
