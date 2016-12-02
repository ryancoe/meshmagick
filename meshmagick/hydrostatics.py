
import numpy as np
import math
from warnings import warn

from mesh_clipper import MeshClipper

__author__ = "Francois Rongere"
__copyright__ = "Copyright 2014-2015, Ecole Centrale de Nantes"
__credits__ = "Francois Rongere"
__licence__ = "CeCILL"
__version__ = "1.0"
__maintainer__ = "Francois Rongere"
__email__ = "Francois.Rongere@ec-nantes.fr"
__status__ = "Development"


# Data for DNV standards
GM_min = 0.15

# TODO: pass this code to a version that only rotates the free surface plane and not the mesh...
# TODO: throw the transformation needed to get the equilibrium from initial position after a successful equilibrium computation
# TODO: make the mesh not to diverge from principal axis


class Force(object):
    def __init__(self, point=(0, 0, 0), value=(0, 0, 0), name='', mode='relative'):
        
        assert len(point) == 3
        assert len(value) == 3
        assert mode in ('relative', 'absolute')
        
        self.point = np.asarray(point, dtype=np.float)
        self.value = np.asarray(value, dtype=np.float)
        self.name = str(name)
        self.mode = mode
    
    def __str__(self):
        str_repr = "Force: %s\n\tPoint: %s\n\tValue: %s\n\tMode: %s" % (self.name, self.point, self.value, self.mode)
        return str_repr
    
    def update(self, dz=0., rot=np.eye(3, dtype=np.float)):
        self.point[2] += dz
        self.point = np.dot(rot, self.point)
        if self.mode == 'relative':
            self.value = np.dot(rot, self.value)
        return
    
    def update_xy(self, dx, dy):
        self.point[0] += dx
        self.point[1] += dy
        return
    
    @property
    def hs_force(self):
        fz = self.value[2]
        moment = np.cross(self.point, self.value)
        mx, my = moment[:2]
        return np.array([fz, mx, my], dtype=np.float)
    
    def reset(self): # TODO: a appeler depuis le reset de Hydrostatics
        raise NotImplementedError
    

class Hydrostatics(object):
    # TODO: refactor this docstring
    """
    Class to perform hydrostatic computations on meshes.
    
    Rules:
    ------
    *** At class instantiation, no modification on the mesh position is done and hydrostatic properties are accessible directly for this position. The mesh may not be at equilibrium thought and residual force balance between hydrostatic force and gravity force may be not null. To trig the equilibrium computations, we have to call the equilibrate() method.
    
       Note that it is useless to call any method to get the hydrostatic properties up to date as it is done internally and automatically at each modification.
    
    *** Intrinsic mesh properties are
    
        - _mass
        - cog
        - zg
        - rho_water
        - gravity
        
        Setting one of these property by its setter will trig a search for a new mesh position that fullfill the hydrostatic equilibrium.
        Note that zg is mandatory to get the hydrostatic stiffness matrix. By default, be carefull that it is set to zero at instantiation.
    
    *** Modification of the displacement will produce the mesh to move along z so that
    it reaches the correct displacement. The _mass is then set accordingly and equals the displacement. Note that this is different from modifying the _mass and
    
    
    *** Setting the buoyancy center will trig a search for a position of the gravity center that fullfill this hydrostatic property, while keeping the correct displacement. NOT IMPLEMENTED, THIS IS AN ADVANCED FEATURE
    
    """
    def __init__(self, mesh, cog=np.zeros(3, dtype=np.float), zg=0., mass=None, rho_water=1023, grav=9.81,
                 verbose=False, animate=False):
        
        # FIXME: l'argument zg n'est pas utilise !
        self.backup = dict()
        
        self.backup['init_mesh'] = mesh.copy()
        self.mesh = mesh.copy()
        
        cog = np.array(cog, dtype=np.float)
        assert cog.shape[0] == 3
        self.backup['gravity_center'] = cog.copy()
        self._gravity_center = cog.copy()
        self._rho_water = rho_water
        self._gravity = grav
        
        self._rhog = rho_water * grav
        
        # Solver parameters
        self._solver_parameters = {'reltol': 1e-2,
                                   'itermax': 100,
                                   'max_nb_restart': 10,
                                   'theta_relax': 2,
                                   'z_relax': 0.1,
                                   'stop_at_unstable': False}
        
        # TODO: ajouter le calcul du tirant d'eau et d'air
        self.hs_data = dict()
        self._update_hydrostatic_properties()
        
        if mass:
            self.mass = mass * 1000. # conversion in kg
        else:
            self._mass = self.hs_data['disp_mass']
        
        self._mg = self._mass * self._gravity
        
        self._verbose = verbose
        
        self.animate = animate
        
        self._rotation = np.eye(3, dtype=np.float)
        
        self.additional_forces = []
        
    @property
    def verbose(self):
        return self._verbose
    
    def verbose_on(self):
        self._verbose = True
        return
    
    def verbose_off(self):
        self._verbose = False
        return
    
    @property
    def gravity(self):
        return self._gravity
    
    @gravity.setter
    def gravity(self, value):
        self._gravity = float(value)
        self._rhog = self._rho_water * value
        self._mg = self._mass * value
        self._update_hydrostatic_properties()
        return
    
    @property
    def rho_water(self):
        return self._rho_water
    
    @rho_water.setter
    def rho_water(self, value):
        self._rho_water = float(value)
        self._rhog = value * self._gravity
        self._update_hydrostatic_properties()
        return
    
    @property
    def mass(self):
        return self._mass / 1000.
    
    @mass.setter
    def mass(self, value):
        
        self._mass = float(value) * 1000.  # Conversion from tons to kg
        self._mg = self._mass * self._gravity  # SI units
        
        if self.is_sinking():
            raise ValueError('%s is sinking as it is too heavy.' % self.mesh.name)
        
        return
    
    def _max_displacement(self):
        return self._rho_water * self.mesh._compute_volume() # in kg
    
    def is_sinking(self):
        if self._mass > self._max_displacement():
            return True
        else:
            return False
    
    @property
    def gravity_center(self):
        return self._gravity_center
    
    @gravity_center.setter
    def gravity_center(self, value):
        value = np.asarray(value, dtype=np.float)
        self.backup['gravity_center'] = value
        assert value.shape[0] == 3
        self._gravity_center = value
        self._update_hydrostatic_properties()
        return
    
    @property
    def zg(self):
        return self._gravity_center[-1]
    
    @zg.setter
    def zg(self, value):
        self._gravity_center[-1] = float(value)
        self._update_hydrostatic_properties()
        return
    
    @property
    def wet_surface_area(self):
        return self.hs_data['wet_surface_area']
    
    @property
    def displacement_volume(self):
        return self.hs_data['disp_volume']
    
    @property
    def displacement(self):
        return self.hs_data['disp_mass'] / 1000.
    
    @property
    def buoyancy_center(self):
        return self.hs_data['buoy_center']
    
    @property
    def flotation_surface_area(self):
        return self.hs_data['waterplane_area']
    
    @property
    def flotation_center(self):
        return self.hs_data['flotation_center']
    
    @property
    def transversal_metacentric_radius(self):
        return self.hs_data['transversal_metacentric_radius']
    
    @property
    def longitudinal_metacentric_radius(self):
        return self.hs_data['longitudinal_metacentric_radius']
    
    @property
    def transversal_metacentric_height(self):
        return self.hs_data['gm_x']
    
    @property
    def longitudinal_metacentric_height(self):
        return self.hs_data['gm_y']
    
    @property
    def hydrostatic_stiffness_matrix(self):
        return self.hs_data['stiffness_matrix']

    @property
    def hydrostatic_mesh(self):
        return self.hs_data['clipper'].clipped_mesh
    
    def reset(self):
        
        # TODO: Utiliser plutot la rotation generale pour retrouver le maillage initial
        
        self.mesh = self.backup['init_mesh'].copy()
        self._gravity_center = self.backup['gravity_center'].copy()
        self._reinit_clipper()
        
        self._update_hydrostatic_properties()
        
        self._rotation = np.eye(3, dtype=np.float)
        return
    
    def is_stable_in_roll(self):
        return self.transversal_metacentric_height > 0.
        
    def is_stable_in_pitch(self):
        return self.longitudinal_metacentric_height > 0.
    
    def isstable(self):
        return self.is_stable_in_pitch() and self.is_stable_in_roll()
    
    def is_at_equilibrium(self):
        
        residual = self.residual
        
        mg = self._mg
        breadth = self.hs_data['breadth']
        lwl = self.hs_data['lwl']
        scale = np.array([mg, mg * breadth, mg * lwl])
        
        if np.all(np.fabs(residual/scale) < self._solver_parameters['reltol']):
            return True
        else:
            return False
    
    @property
    def delta_fz(self):
        fz, _, _ = self.residual
        return fz
    
    @property
    def delta_mx(self):
        _, mx, _ = self.residual
        return mx
    
    @property
    def delta_my(self):
        _, _, my = self.residual
        return my
    
    # TODO: create a Hydrostatic stiffness matrix class which should be a symmetric array class
    @property
    def S33(self):
        return self.hs_data['stiffness_matrix'][0, 0]
    
    @property
    def S34(self):
        return self.hs_data['stiffness_matrix'][0, 1]
    
    @property
    def S35(self):
        return self.hs_data['stiffness_matrix'][0, 2]
    
    @property
    def S44(self):
        return self.hs_data['stiffness_matrix'][1, 1]
    
    @property
    def S45(self):
        return self.hs_data['stiffness_matrix'][1, 2]
    
    @property
    def S55(self):
        return self.hs_data['stiffness_matrix'][2, 2]
    
    @property
    def reltol(self):
        return self._solver_parameters['reltol']
    
    @reltol.setter
    def reltol(self, value):
        value = float(value)
        assert 0. < value < 1.
        self._solver_parameters['reltol'] = value
        return
    
    @property
    def theta_relax(self):
        return self._solver_parameters['theta_relax']
    
    @theta_relax.setter
    def theta_relax(self, value):
        value = float(value)
        assert 0. < value < 10.
        self._solver_parameters['theta_relax'] = value
        return
        
    @property
    def z_relax(self):
        return self._solver_parameters['z_relax']
    
    @z_relax.setter
    def z_relax(self, value):
        value = float(value)
        assert 0. < value < 1.
        self._solver_parameters['z_relax'] = value
        return
    
    @property
    def max_iterations(self):
        return self._solver_parameters['itermax']
    
    @max_iterations.setter
    def max_iterations(self, value):
        value = int(value)
        assert value > 0.
        self._solver_parameters['itermax'] = value
        return
    
    @property
    def max_restart(self):
        return self._solver_parameters['max_nb_restart']
    
    @max_restart.setter
    def max_restart(self, value):
        value = int(value)
        assert value >= 0.
        self._solver_parameters['max_nb_restart'] = value
        return
    
    @property
    def allow_unstable(self):
        return self._solver_parameters['stop_at_unstable']
    
    @allow_unstable.setter
    def allow_unstable(self, value):
        value = bool(value)
        self._solver_parameters['stop_at_unstable'] = value
        return
    
    def allow_unstable_on(self):
        self.allow_unstable = True
        return
    
    def allow_unstable_off(self):
        self.allow_unstable = False
        return
    
    def _reinit_clipper(self):
        try:
            del self.hs_data['clipper']
        except KeyError:
            pass
        return
    
    def _update_hydrostatic_properties(self):
        """Updates the hydrostatics properties of the mesh.
        """
    
        eps = 1e-4  # For zeroing tiny coefficients in the hydrostatic stiffness matrix
    
        # Clipping the mesh by the Oxy plane
        # TODO: ne pas recreer une instance de MeshClipper a fois mais la stocker et mettre a jour son maillage ainsi
        #  que ses donnees
        
        # FIXME: on ne devrait recouper le maillage que si ce dernier a ete modifie !!!
        try:
            clipper = self.hs_data['clipper']
            clipped_mesh = clipper.clipped_mesh
        except KeyError:
            clipper = MeshClipper(self.mesh, assert_closed_boundaries=True, verbose=False)
            self.hs_data['clipper'] = clipper
            clipped_mesh = clipper.clipped_mesh
            
        # Retrieving faces properties for the clipped mesh
        areas = clipped_mesh.faces_areas
        # normals = clipped_mesh.faces_normals
        # centers = clipped_mesh.faces_centers
        
        if np.any(np.fabs(areas) < 1e-10):  # TODO: bloc a retirer
            print 'probleme de facette'
            self.mesh.quick_save()
            raise Exception
        
        wet_surface_area = areas.sum()
    
        inertia = clipped_mesh.eval_plain_mesh_inertias(rho_medium=self.rho_water)
        xb, yb, zb = inertia.gravity_center
        disp_volume = inertia.mass / self.rho_water
        
        # Computing quantities from intersection polygons
        sigma0 = 0.  # \iint_{waterplane_area} dS = waterplane_area
        sigma1 = 0.  # \iint_{waterplane_area} x dS
        sigma2 = 0.  # \iint_{waterplane_area} y dS
        sigma3 = 0.  # \iint_{waterplane_area} xy dS
        sigma4 = 0.  # \iint_{waterplane_area} x^2 dS
        sigma5 = 0.  # \iint_{waterplane_area} y^2 dS
        
        xmin = []
        xmax = []
        ymin = []
        ymax = []
        
        polygons = clipper.closed_polygons
        for polygon in polygons:
            polyverts = clipper.clipped_crown_mesh.vertices[polygon]
            
            # TODO: voir si on conserve ce test...
            if np.any(np.fabs(polyverts[:, 2]) > 1e-3):
                print 'The intersection polygon is not on the plane z=0'
        
            xi, yi = polyverts[0, :2]
            for (xii, yii) in polyverts[1:, :2]:
                dx = xii - xi
                dy = yii - yi
                px = xi + xii
                py = yi + yii
                a = xi * xi + xii * xii
            
                sigma0 += dy * px
                sigma1 += dy * (px * px - xi * xii)
                sigma2 += dx * (py * py - yi * yii)
                sigma3 += dy * (py * a + 2 * px * (xi * yi + xii * yii))
                sigma4 += dy * a * px
                sigma5 += dx * (yi * yi + yii * yii) * py
            
                xi, yi = xii, yii
        
            xmin.append(polyverts[:, 0].min())
            xmax.append(polyverts[:, 0].max())
            ymin.append(polyverts[:, 1].min())
            ymax.append(polyverts[:, 1].max())
    
        minx, maxx = [min(xmin), max(xmax)]
        miny, maxy = [min(ymin), max(ymax)]
    
        sigma0 /= 2
        sigma1 /= 6
        sigma2 /= -6
        sigma3 /= 24
        sigma4 /= 12
        sigma5 /= -12
    
        # Flotation surface
        waterplane_area = sigma0
        
        # Stiffness matrix coefficients that do not depend on the position of the gravity center
        rhog = self._rhog
        s33 = rhog * waterplane_area
        s34 = rhog * sigma2
        s35 = -rhog * sigma1
        s45 = -rhog * sigma3
    
        # Metacentric radius (Bouguer formulae)
        transversal_metacentric_radius = sigma5 / disp_volume  # Around Ox
        longitudinal_metacentric_radius = sigma4 / disp_volume  # Around Oy
    
        # Metacentric height
        a = self.zg - zb  # BG
        gm_x = transversal_metacentric_radius - a
        gm_y = longitudinal_metacentric_radius - a
    
        # Stiffness matrix coefficients that depend on the position of the gravity center
        s44 = rhog * disp_volume * gm_x
        s55 = rhog * disp_volume * gm_y
    
        # Assembling stiffness matrix
        stiffness_matrix = np.array([[s33, s34, s35],
                                     [s34, s44, s45],
                                     [s35, s45, s55]], dtype=np.float)
        
        # Zeroing tiny coefficients
        stiffness_matrix[np.fabs(stiffness_matrix) < eps] = 0.
    
        # Flotation center F:
        x_f = -s35 / s33
        y_f = s34 / s33
        
        xmin, xmax, ymin, ymax, zmin, zmax = clipped_mesh.axis_aligned_bbox
        
        # Storing data
        self.hs_data['wet_surface_area'] = wet_surface_area
        self.hs_data['disp_volume'] = disp_volume
        self.hs_data['disp_mass'] = self._rho_water * disp_volume
        self.hs_data['buoy_center'] = np.array([xb, yb, zb], dtype=np.float)
        self.hs_data['flotation_center'] = np.array([x_f, y_f, 0.], dtype=np.float)
        self.hs_data['waterplane_area'] = waterplane_area
        self.hs_data['transversal_metacentric_radius'] = transversal_metacentric_radius
        self.hs_data['longitudinal_metacentric_radius'] = longitudinal_metacentric_radius
        self.hs_data['gm_x'] = gm_x
        self.hs_data['gm_y'] = gm_y
        self.hs_data['stiffness_matrix'] = stiffness_matrix
        self.hs_data['lwl'] = maxx - minx
        self.hs_data['los'] = xmax - xmin
        self.hs_data['bos'] = ymax - ymin
        self.hs_data['draught'] = math.fabs(zmin)
        self.hs_data['fp'] = maxx
        self.hs_data['breadth'] = maxy - miny
        
        # TODO: we should better store the inertia object !
        inertia.shift_at_cog()
        self.hs_data['Ixx'] = inertia.xx
        self.hs_data['Iyy'] = inertia.yy
        self.hs_data['Izz'] = inertia.zz
        self.hs_data['Ixy'] = inertia.xy
        self.hs_data['Ixz'] = inertia.xz
        self.hs_data['Iyz'] = inertia.yz
    
        return
    
    def get_gravity_force(self):
        return Force(point=self._gravity_center, value=[0, 0, -self._mass*self._gravity], mode='absolute')
    
    def get_buoyancy_force(self):
        value = [0, 0, self.rho_water*self._gravity*self.displacement_volume]
        return Force(point=self.buoyancy_center, value=value, mode='absolute')
            
    def add_force(self, force):
        # TODO: allow to remove those forces...
        assert isinstance(force, Force)
        self.additional_forces.append(force)
        return
    
    @property
    def scale(self):
        mg = self._mg
        breadth = self.hs_data['breadth']
        lwl = self.hs_data['lwl']
        scale = np.array([mg, mg * breadth, mg * lwl])
        return scale

    @property
    def residual(self):
        rhog_v = self._rhog * self.hs_data['disp_volume']
        mg = self._mg
    
        xb, yb, _ = self.hs_data['buoy_center']
        xg, yg, _ = self._gravity_center
    
        residual = np.array([rhog_v - mg,
                             rhog_v * yb - mg * yg,
                             -rhog_v * xb + mg * xg])
        
        # Accounting for additional forces in the static equilibrium
        for force in self.additional_forces:
            residual += force.hs_force
        
        return residual
    
    def set_displacement(self, disp):
        """
        Displaces mesh at a prescribed displacement and returns

        Parameters
        ----------
        disp : float
            Mass displacement of the hull (in tons)
        """
        
        if self.verbose:
            print "\nComplying with a displacement of %.3f tons" % disp
            print "----------------------------------------------"
        
        self.mass = disp
        
        itermax = self._solver_parameters['itermax']
        reltol = self._solver_parameters['reltol']
        z_relax = self._solver_parameters['z_relax']
        
        dz = 0.
        iter = 0

        while True:
            # print iter
            if iter == itermax:
                if self.verbose:
                    print '\t-> No convergence of the displacement after %u iterations' % itermax
                break
            
            # Translating the mesh
            self.mesh.translate_z(dz)
            self._gravity_center[2] += dz
            
            for force in self.additional_forces:
                force.update(dz=dz)
            
            self._reinit_clipper()
            self._update_hydrostatic_properties()
    
            residual = self.delta_fz
            if math.fabs(residual / self._mg) < reltol:
                if self.verbose:
                    print '\t-> Convergence obtained after %u iterations' % iter
                break
            
            dz = residual / (self._rhog * self.flotation_surface_area)
            if math.fabs(dz) > z_relax:
                dz = math.copysign(z_relax, dz)
            iter += 1
        
        return

    def equilibrate(self, init_disp=True):
        
        # Initial displacement equilibrium
        if init_disp:
            if self.verbose:
                print "First placing the mesh at the target displacement"
                print "-------------------------------------------------"
            self.set_displacement(self.mass)
        
        if self.verbose:
            print '\nComputing equilibrium from initial condition.'
            print '----------------------------------------------'
        
        # Retrieving solver parameters
        z_relax = self._solver_parameters['z_relax']
        theta_relax = self._solver_parameters['theta_relax']
        theta_relax_x = math.radians(theta_relax)
        theta_relax_y = math.radians(theta_relax)
        
        itermax = self._solver_parameters['itermax']
        reltol = self._solver_parameters['reltol']
        max_nb_restart = self._solver_parameters['max_nb_restart']
        
        rhog = self._rhog
        mg = self._mg
        
        # Initialization
        dz = thetax = thetay = 0.
        iter = nb_restart = 0
        unstable_config = False
    
        while True:
            # print '\n', iter
            if unstable_config or (iter == (nb_restart + 1) * (itermax-1)):
                if self.verbose:
                    if unstable_config:
                        print 'Unstable equilibrium reached.'
                        print '\t-> Keep searching a stable configuration by random restart number %u.' % (nb_restart+1)
                    else:
                        print 'Failed to find an equilibrium configuration with these initial conditions in %u ' \
                              'iterations.' % itermax
                        print '\t-> Keep searching by random restart number %u.' % (nb_restart+1)
                
                unstable_config = False
                
                # Max iterations reached
                if nb_restart < max_nb_restart-1:
                    nb_restart += 1
                    # Random on the position of the body
                    thetax, thetay = np.random.rand(2) * math.pi
                    rot_matrix = self.mesh.rotate([thetax, thetay, 0.])
                    self._gravity_center = np.dot(rot_matrix, self._gravity_center)
                    self._rotation = np.dot(rot_matrix, self._rotation)
                    self._reinit_clipper()
                    self._update_hydrostatic_properties()
                    
                    for force in self.additional_forces:
                        force.update(rot=rot_matrix)
                    
                    dz = thetax = thetay = 0.
                    
                else:
                    # Max number of restart allowed. Failed to find an equilibrium configuration.
                    code = 0
                    break
        
            # Applying transformation to the mesh
            self.mesh.translate_z(dz)
            self._gravity_center[2] += dz
            
            rot_matrix = self.mesh.rotate([thetax, thetay, 0.])
            self._gravity_center = np.dot(rot_matrix, self._gravity_center)
            self._rotation = np.dot(rot_matrix, self._rotation)
            
            # Updating force data
            for force in self.additional_forces:
                force.update(dz=dz, rot=rot_matrix)
            
            self._reinit_clipper()
            self._update_hydrostatic_properties()

            # if self.animate:
            #     mmio.write_VTP('mesh%u.vtp' % iter, mymesh_c.vertices, mymesh_c.faces)
        
            residual = self.residual
            scale = self.scale
            
            if np.all(np.fabs(self.residual / scale) < reltol):
                # Convergence at an equilibrium
                if self.isstable():
                    # Stable equilibrium
                    code = 1
                    break
                else:
                    if self._solver_parameters['stop_at_unstable']:
                        # Unstable configuration reached
                        code = 2
                        break
                    # TODO: mettre une option permettant de choisir si on s'arrete a des configs instables
                    else:
                        # We force the restart with an other random orientation as initial condition
                        unstable_config = True
                        iter += 1
                        continue
                    
            # Computing correction
            # TODO: voir pour une resolution ne faisant pas intervenir np.linalg ?
            stiffness_matrix = self.hs_data['stiffness_matrix']
            dz, thetax, thetay = np.linalg.solve(stiffness_matrix, residual)
        
            # Relaxation
            if math.fabs(dz) > z_relax:
                dz = math.copysign(z_relax, dz)
        
            if math.fabs(thetax) > theta_relax_x:
                thetax = math.copysign(theta_relax_x, thetax)
        
            if math.fabs(thetay) > theta_relax_y:
                thetay = math.copysign(theta_relax_y, thetay)
        
            iter += 1
    
        # Zeroing xcog and ycog
        self.mesh.translate([-self._gravity_center[0], -self._gravity_center[1], 0.])
        self.hs_data['buoy_center'][:2] -= self._gravity_center[:2]
        
        for force in self.additional_forces:
            force.update_xy(-self._gravity_center[0], -self._gravity_center[1])
            
        self._gravity_center[:2] = 0.
        
        if self.verbose:
            if code == 0:
                print "\t-> Maximum number of restart reached. Failed to find an equilibrum position."
            elif code == 1:
                print "Stable equilibrium reached after %u iterations and %u random restart" % (iter, nb_restart)
            elif code == 2:
                print 'Unstable equilibrium reached after %u iterations and %u random restart' % (iter, nb_restart)
        
        return code

    def get_hydrostatic_report(self):
        
        def header(title):
            head = '\t-----------------------------------------------------\n'
            head += '\t* {0}\n'.format(title.upper())
            head += '\t-----------------------------------------------------\n'
            return head
        
        def hspace():
            return '\n'
        
        def build_line(text, data, precision=3, dtype='f'):
            # TODO: ajouter unit
            textwidth = 40
            try:
                line = '\t{:-<{textwidth}}>  {:< .{precision}{dtype}}\n'.format(str(text).upper(), data,
                                                                         precision=precision, textwidth=textwidth,
                                                                         dtype=dtype
                                                                        )
            except ValueError:
                if isinstance(data, np.ndarray):
                    if data.ndim == 1:
                        data_str = ''.join(['{:< 10.{precision}{dtype}}'.format(val, precision=precision, dtype=dtype)
                                            for val in data])
                        line = '\t{:-<{textwidth}}>  {}\n'.format(str(text).upper(), data_str, textwidth=textwidth)
                        
                    # else:
                    #     print data
            
            return line
        
        # TODO: ajouter la reference au point de calcul de la matrice raideur
        
        msg = '\n'
        # title = 'Hydrostatic report ({0})\n\tGenerated by meshmagick on {1}'.format(self.mesh.name, strftime('%c')).upper()
        # msg += header(title)
        
        msg += hspace()
        msg += build_line('Gravity acceleration (M/S**2)', self.gravity, precision=2)
        msg += build_line('Density of water (kg/M**3)', self.rho_water, precision=1)
        
        msg += hspace()
        msg += build_line('Waterplane area (M**2)', self.flotation_surface_area, precision=1)
        msg += build_line('Waterplane center (M)', self.flotation_center[:2], precision=3)
        msg += build_line('Wet area (M**2)', self.wet_surface_area, precision=1)
        msg += build_line('Displacement volume (M**3)', self.displacement_volume, precision=3)
        msg += build_line('Displacement mass (tons)', self.displacement, precision=3)
        msg += build_line('Buoyancy center (M)', self.buoyancy_center, precision=3)
        msg += build_line('Center of gravity (M)', self.gravity_center, precision=3)
        
        msg += hspace()
        msg += build_line('Draught (M)', self.hs_data['draught'], precision=3) # TODO
        msg += build_line('Length overall submerged (M)', self.hs_data['los'], precision=2)
        msg += build_line('Breadth overall submerged (M)', self.hs_data['bos'], precision=2)
        msg += build_line('Length at Waterline LWL (M)', self.hs_data['lwl'], precision=2)
        msg += build_line('Forward perpendicular (M)', self.hs_data['fp'], precision=2)
        
        msg += hspace()
        msg += build_line('Transversal metacentric radius (M)', self.transversal_metacentric_radius, precision=3)
        msg += build_line('Transversal metacentric height GMt (M)', self.transversal_metacentric_height, precision=3)
        msg += build_line('Longitudinal metacentric radius (M)', self.longitudinal_metacentric_radius, precision=3)
        msg += build_line('Longitudinal metacentric height GMl (M)', self.longitudinal_metacentric_height, precision=3)
        
        msg += hspace()
        msg += '\tHYDROSTATIC STIFFNESS COEFFICIENTS:\n'
        msg += build_line('K33 (N/M)', self.S33, precision=4, dtype='E')
        msg += build_line('K34 (N)', self.S34, precision=4, dtype='E')
        msg += build_line('K35 (N)', self.S35, precision=4, dtype='E')
        msg += build_line('K44 (N.M)', self.S44, precision=4, dtype='E')
        msg += build_line('K45 (N.M)', self.S45, precision=4, dtype='E')
        msg += build_line('K55 (N.M)', self.S55, precision=4, dtype='E')
        
        # Il faut faire une correction avec le plan de la flottaison de certains coeffs
        msg += hspace()
        msg += '\tINERTIAS:\n'
        msg += build_line('Ixx', self.hs_data['Ixx'], precision=3, dtype='E')
        msg += build_line('Ixy', self.hs_data['Ixy'], precision=3, dtype='E')
        msg += build_line('Ixz', self.hs_data['Ixz'], precision=3, dtype='E')
        msg += build_line('Iyy', self.hs_data['Iyy'], precision=3, dtype='E')
        msg += build_line('Iyz', self.hs_data['Iyz'], precision=3, dtype='E')
        msg += build_line('Izz', self.hs_data['Izz'], precision=3, dtype='E')
        
        msg += hspace()
        msg += '\tRESIDUALS:\n'
        msg += build_line('Absolute', self.residual, precision=3, dtype='E')
        msg += build_line('Relative', self.residual/self.scale, precision=3, dtype='E')
        msg += build_line('Relative tolerance', self.reltol, precision=1, dtype='E')
        # residual = self.residual
        # msg += ('\nResidual:\n')
        # msg += ('Delta Fz = %.3f N\n' % residual[0])
        # msg += ('Delta Mx = %.3f Nm\n' % residual[1])
        # msg += ('Delta My = %.3f Nm\n' % residual[2])
        #
        # rel_res = residual / self.scale
        # msg += ('\nRelative residual:\n')
        # msg += ('Delta Fz = %E\n' % rel_res[0])
        # msg += ('Delta Mx = %E\n' % rel_res[1])
        # msg += ('Delta My = %E\n' % rel_res[2])
        # msg += ('Relative tolerance of the solver: %.1E\n' % self.reltol)
        
        return msg
    
    
    # FIXME: la methode show ne devrait pas faire appel explicitement a des fonctions vtk...
    # Tout devrait etre gere dans MMViewer
    def show(self):
        # TODO: Ce n'est pas ce module qui doit savoir utiliser vtk !!!
        
        import MMviewer
        import vtk
        
        vtk_polydata = self.mesh._vtk_polydata()
        self.viewer = MMviewer.MMViewer()
        self.viewer.add_polydata(vtk_polydata)
        
        pd_orig = self.viewer.add_point([0, 0, 0], color=[0, 0, 0])
        
        pd_cog = self.viewer.add_point(self.gravity_center, color=[1, 0, 0])
        
        pd_orig_cog = self.viewer.add_line([0, 0, 0], self.gravity_center, color=[1, 0, 0])
        
        pd_buoy = self.viewer.add_point(self.buoyancy_center, color=[0, 1, 0])

        pd_orig_buoy = self.viewer.add_line([0, 0, 0], self.buoyancy_center, color=[0, 1, 0])
        
        scale = self.mass*1000
        
        # Adding glyph for gravity force
        gforce = self.get_gravity_force()
        self.viewer.add_vector(gforce.point, gforce.value, scale=scale, color=[1, 0, 0])
        
        # Adding glyph for buoyancy force
        bforce = self.get_buoyancy_force()
        self.viewer.add_vector(bforce.point, bforce.value, scale=scale, color=[0, 1, 0])
        
        # Adding glyph for additional forces
        for force in self.additional_forces:
            self.viewer.add_point(force.point, color=[0, 0, 1])
            self.viewer.add_vector(force.point, force.value, scale=scale, color=[0, 0, 1])
        
        # TODO: mettre la suite dans une methode de MMViewer
        # Adding corner annotation
        ca = vtk.vtkCornerAnnotation()
        ca.SetLinearFontScaleFactor(2)
        ca.SetNonlinearFontScaleFactor(1)
        ca.SetMaximumFontSize(20)
        labels = "Origin: Black; Gravity Center: Red; Buoyancy Center: Green\nTo see points, press 'w'"
        ca.SetText(2, labels)
        ca.GetTextProperty().SetColor(0., 0., 0.)
        self.viewer.renderer.AddViewProp(ca)
        
        # Showing the viewer
        self.viewer.show()
        self.viewer.finalize()
        
        return


if __name__ == '__main__':

    # The following code are only for testing purpose
    import mmio
    import sys
    import mesh
    
    vertices, faces = mmio.load_VTP('meshmagick/tests/data/SEAREV.vtp')
    
    searev = mesh.Mesh(vertices, faces, name='SEAREV')
    
    hs = Hydrostatics(searev)
    hs.verbose_on()
    
    # hs.mass = 2300
    hs.gravity_center = [0, 0, -2]
    hs.allow_unstable_off()
    hs.reltol = 1e-3
    
    F = [0, 0, -50e3*9.81]
    force1 = Force(point=[0, 0, 5], value=[0, 1e7, 0], mode='relative')
    # force2 = AdditionalForce(point=[0, 15, -5], value=[0, 0, -50e3*9.81], mode='absolute')
    # force = AdditionalForce(point=[0, 0, 3], value=[0, 1e7, 0], mode='absolute')
    hs.add_force(force1)
    # hs.add_force(force2)
    
    
    hs.equilibrate()
    hs.show()
    
    print hs.get_hydrostatic_report()
    
    print 'Done !'
    
    

