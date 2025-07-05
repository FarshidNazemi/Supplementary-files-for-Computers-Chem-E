import pandas as pd
import numpy as np

from pathlib import Path
from Technology import Technology


class Scenario():
	"""
	Object that calculates scenario-level financial metrics and results.
	"""
	def __init__(
			self,
			production_process : str = 'Barrier Film',
			product            : str = 'Barrier film',
      func_unit          : float = 1.0,
			eol_sc             : dict = {'Landfilling': [1.0, 0]},
			products           : dict = {'Landfilling': 'Landfilled waste'},
			sens_df            : pd.DataFrame = None,
      data_path          : str = 'data',
      data_file          : str = 'TEA-data.xlsx'
			):
		"""
		Instantiate an end-of-life Scenario.

		On instantiation, the Scenario creates the vaulue chain defined by the eol_sc input parameter,
		performs TEA calculations, and stores the results by technology in the value_chain attribute.

		Parameters
		----------
    production_process : str, default='Barrier Film'
			Name of the Technology. Code will break if name is not present in the Design dataset.
    product : str, default='Barrier film'
			Name of the primary product for calculating per-unit production cost. Code will break
			if this product is not present in the Design dataset.
    func_unit : float, default=1.0
      Quantity (lbs) of barrier film in the functional unit. `total_cost` attribute is based on 
			this amount. This is NOT the output of the initial production process, but the output of
      the final recycling process after all EOL cycles are completed.
		eol_sc : dict, default={'Landfilling': [1.0, 0]}
			Fraction of barrier film sent to each EOL process at the end of
			the first lifetime.
			Keys are strings: names of EOL technologies. See TEA-data.xlsx for allowed
			values.
			Items are two-element lists. The first element is the barrier film
			fraction (float, 0-1). The second element is the number of times that EOL
			process is used (int, >=0, number of secondary lifetimes for this barrier film
			fraction). The second element should be 0 unless the process creates a closed loop.
		products : dict, default={'Landfilling': 'Landfilled waste'}
			Name of primary product from each EOL process.
			Keys are strings: EOL process names.
			Items are strings: Primary product of the EOL process.			
		sens_df : pd.DataFrame, Default = None
			Same structure as the design data but with values changed for sensitivity/uncertainty 
			analyses. Ignored if not provided.				
    data_path : str, default='data'
			Absolute or relative path to directory where data file is saved.
		data_file : str, default='TEA-data.xlsx'
			Name of the data file including extension (.xlsx). The data file must have three
			sheets named 'Design', 'Financial', and 'Structure' to read in correctly.
		
		Attributes
		----------
		design : pandas.DataFrame
			Contents of the data_file sheet named Design.
		finan : pandas.DataFrame
			Contents of the data_file sheet named Financial.
		struct : pandas.DataFrame
			Contents of the data_file sheet named Structure.
		value_chain : list of Technology
			List containing Technology instances that defines the end-of-life value
			chain, as defined in the eol_sc input parameter. Each Technology instance
			contains additional Technology attributes that store TEA results and process
			information.
		total_cost : float
			Single number economic summary of the value chain. Calculated by summing each
			Technology's production cost.
		process_production_costs : pandas.DataFrame
			Technology-level production costs labeled with technology name.
		process_annual_costs : pandas.DataFrame
			Technology-level annual costs disaggregated by cost category and labeled with
			technology name. Annual costs are NOT affected by the functional unit; they represent
			the process scale defined in the input dataset.
		
		Returns
		-------
		None
		"""
    # Read in TEA data from XLSX file
		self.design = pd.read_excel(
			Path(data_path) / data_file,
			sheet_name='Design'
		)
		self.finan = pd.read_excel(
			Path(data_path) / data_file,
			sheet_name='Financial'
		)
		self.struct = pd.read_excel(
			Path(data_path) / data_file,
			sheet_name='Structure'
		)

		# If running sens/unc calcs, then replace values in self.design with the
		# sensitivity values
		if sens_df is not None:
			for _, row in sens_df.iterrows():
				self.design.loc[
					(self.design.Index == row.Index) &
					(self.design.Technology == row.Technology) & 
					(self.design.Variable == row.Variable), 'Value'] = row['Value']			

		_prod_eff = self.design[
			['Technology','Value']
			].loc[
				(self.design.Technology == production_process) &
				  (self.design.Variable == 'Output efficiency')
			].Value.values[0]
		
		# Calculate original (virgin) barrier film production amount
		# Loop through eol_sc to calculate X_1 for every EOL process
		# sum the X_1s to get the original production amount
		_virg_prod = 0.0
		_prod_masc = 0.0
		_prod_strap = 0.0
		_prod_amt = 0.0
		for key, value in eol_sc.items():
			_recyc_eff = self.design[
				['Technology','Value']
				].loc[
					(self.design.Technology == key) &
					  (self.design.Variable == 'Output efficiency')
				].Value.values[0]
			_eol_frac = value[0]
			_n_cycles = value[1]
			# Closed-loop systems get a complicated calculation.
			# MASC and STRAP calculations are NOT equivalent; STRAP needs another round through
			# barrier film production while MASC produces ready-to-use barrier film
			if key == 'Mechanical and Solvent Cleaning':
				# amt of initial virgin production
				_virg_prod = _eol_frac * func_unit / (1 + sum([(_recyc_eff)**i for i in range(_n_cycles+1)]))
				# TOTAL amt processed thru MASC
				_prod_masc = sum([_eol_frac * func_unit * (_recyc_eff)**i / (1 + sum([(_recyc_eff)**i for i in range(_n_cycles+1)])) for i in range(_n_cycles+1)])
			elif key == 'Solvent Treatment and Precipitation':
				# this process has a downstream connection that 
				# enables the looping
				_downst = self.struct.Downstream.loc[self.struct.Technology == key].values[0]
				# get efficiency of the downstream process (barrier film production)
				_eff_downst = self.design[
					['Technology','Value']
					].loc[
						(self.design.Technology == _downst) &
						(self.design.Variable == 'Output efficiency')
						].Value.values[0]				
				# amt of initial virgin production
				_virg_prod = _eol_frac * func_unit / (1 + sum([(_eff_downst*(_recyc_eff))**i for i in range(_n_cycles+1)]))
				# TOTAL amt of secondary film made from STRAP-derived materials
				# This is NOT the total amt of film entering or materials leaving STRAP
				_prod_strap = sum([_eol_frac * func_unit * (_eff_downst*(_recyc_eff))**i / (1 + sum([(_eff_downst*(_recyc_eff))**i for i in range(_n_cycles+1)])) for i in range(_n_cycles+1)])
			else:
				# Otherwise, the production amount assigned to this technology is just the functional unit times
				# the fraction sent to this technology.
				_prod_amt = _prod_amt + func_unit * _eol_frac
				_virg_prod = func_unit
		
		# Create value_chain attribute (list) and populate with the Technology instance
		# that begins the value chain - this is virgin production of barrier film
		self.value_chain = [
			Technology(
				name=production_process,
				product=product,
				design_data=self.design,
				financial_data=self.finan,
				output=_virg_prod
			)
		]
		self.value_chain[0].name = production_process + ', initial'

		# Again loop through eol_sc
		# This time to instantiate EOL technologies and add to the value_chain list
		for key, value in eol_sc.items():
			_eol_frac = value[0]
			_n_cycles = value[1]
			_recyc_eff = self.design[
				['Technology','Value']
				].loc[
					(self.design.Technology == key) &
					  (self.design.Variable == 'Output efficiency')
				].Value.values[0]			
			# Use production amounts to instantiate and append the relevant Technologies
			if key == 'Mechanical and Solvent Cleaning':
				self.value_chain.append(
					Technology(
						name=key,
						product=products[key],
						design_data=self.design,
						financial_data=self.finan,
						output=_prod_masc
					)
				)
				self.eol_film_prod = _prod_masc
				self.eol_polyethylene_prod = 0.0
				# Add final landfilling step to dispose of all film at end of cycles
				_film_to_landfill = _virg_prod * _eol_frac * (_recyc_eff)**(_n_cycles)
			elif key == 'Solvent Treatment and Precipitation':
				self.value_chain.append(
					Technology(
						name=key,
						product=products[key],
						design_data=self.design,
						financial_data=self.finan,
						output=0.7*_prod_strap/_eff_downst
					)
				)
				self.eol_film_prod = _prod_strap
				self.eol_polyethylene_prod = 0.7*_prod_strap/_eff_downst
				_downst_film = Technology(
						name=_downst,
						product='Barrier film',
						initial = False,
						design_data=self.design,
						financial_data=self.finan,
						output=_prod_strap
					)
				# Add final landfilling step to dispose of all film at end of cycles
				_film_to_landfill = _virg_prod * _eol_frac * ((_recyc_eff)*_eff_downst)**(_n_cycles)
				# Update financial data attribute to calculate new SMC production cost
				self.finan.loc[
					self.finan.Index == 'Barrier film',
					'Value'
				] = _downst_film.net_normalized_costs
				# Add downstream barrier film production to value chain
				self.value_chain.append(
					_downst_film
				)
			else:
				self.eol_film_prod = func_unit*_eol_frac
				self.eol_polyethylene_prod = 0.0
				self.value_chain.append(
					Technology(
						name=key,
						product=products[key],
						design_data=self.design,
						financial_data=self.finan,
						output=func_unit*_eol_frac
					)
				)
				if key not in ['Landfilling', 'Incineration', 'Pyrolysis']:
					# Add final landfilling step to dispose of all film at end of cycles
					_film_to_landfill = _virg_prod * _eol_frac * (_recyc_eff)
				else:
					# If landfilling is the EOL option, no "final landfilling"
					_film_to_landfill = 0.0

			# Add final landfilling step to dispose of all film at end of cycles
			if _film_to_landfill != 0.0:
				_final_landfill = Technology(
					name='Landfilling',
					product='Landfilled waste',
					design_data=self.design,
					financial_data=self.finan,
					output=_film_to_landfill
				)
				# Update name to distinguish from landfilling before cycline
				_final_landfill.name = 'Landfilling, final'
				self.value_chain.append(
					_final_landfill
				)

		# Use the Technology-level attributes in value_chain to create additional
		# Scenario-level attributes that can be accessed directly rather than by
		# using list comprehensions

		# Single number summary: total production costs over all technologies
		self.total_eol_cost = sum([i.production_cost for i in self.value_chain if i.name not in ['Sheet Molding Compound','Barrier Film, initial']])
		self.total_cost = sum([i.production_cost for i in self.value_chain])

		self.virgin_prod = _virg_prod
		self.final_landfill = _film_to_landfill

		# Production costs disaggregated by process/technology
		_proc_prod_costs = pd.DataFrame(
		).from_dict(
			{i.name: i.production_cost for i in self.value_chain},
			  orient='index'
		)

		_proc_prod_costs.reset_index(inplace=True)
		self.process_production_costs = _proc_prod_costs.rename(
			columns={'index':'Technology',0:'Production Cost (USD)'}
		)

		# Annual costs disaggregated by process/technology
		_proc_ann_costs = pd.concat(
			[i.annual_costs for i in self.value_chain],
			  ignore_index=True
		)
		_proc_ann_costs['Technology'] = np.array(
			[np.repeat(i.name, len(i.annual_costs)) for i in self.value_chain]
			).flatten()
		_proc_ann_costs.rename(
			columns={'index':'Category','Value':'Annual Cost (USD)'},
			  inplace=True
				)
		self.process_annual_costs = _proc_ann_costs[
			['Technology','Category','Annual Cost (USD)']
			]