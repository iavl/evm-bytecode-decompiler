pragma solidity ^0.8.0;
contract ERC20Fixture { mapping(address => uint256) public balanceOf; event Transfer(address indexed from, address indexed to, uint256 value); function mint(uint256 value) external { balanceOf[msg.sender] += value; emit Transfer(address(0), msg.sender, value); } }
